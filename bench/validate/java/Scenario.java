import java.io.BufferedWriter;
import java.io.IOException;
import java.io.RandomAccessFile;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.List;

/**
 * The events that every logging library writes, and the record of what was written.
 *
 * <p>The record (the oracle) has one tab-separated line per event: the number, the level, the kind, the first line
 * of the message, how many lines the event added to the log file, the wall-clock times just before and just
 * after the call, and the first line of the exception (empty without one). The number of lines is counted from the growth of the file itself, so the boundaries of the events
 * do not depend on any parser.
 */
public final class Scenario {
    /** One library's way to write an event. */
    public interface Sink {
        void log(String level, String message, Throwable error);

        void put(String key, String value);

        void clear();

        void thread(String name, Runnable work) throws InterruptedException;
    }

    private static final DateTimeFormatter STAMP = DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss.SSS");
    private static final String[] LEVELS = {"TRACE", "DEBUG", "INFO", "WARN", "ERROR"};

    private final Sink sink;
    private final RandomAccessFile file;
    private final List<String> oracle = new ArrayList<>();
    private long offset;

    private Scenario(Sink sink, RandomAccessFile file) {
        this.sink = sink;
        this.file = file;
    }

    static Throwable chain(int number) {
        try {
            level1(number);
        } catch (RuntimeException outer) {
            outer.addSuppressed(new IllegalArgumentException("suppressed " + number));
            return outer;
        }
        return null;
    }

    private static void level1(int number) {
        try {
            level2(number);
        } catch (IllegalStateException middle) {
            throw new RuntimeException("outer " + number, middle);
        }
    }

    private static void level2(int number) {
        try {
            level3(number);
        } catch (java.io.IOException root) {
            throw new IllegalStateException("middle " + number, root);
        }
    }

    private static void level3(int number) throws java.io.IOException {
        throw new java.io.IOException("root cause " + number);
    }

    /** Write the events of {@code rounds} rounds to the log at {@code logPath} and the record to {@code oraclePath}. */
    public static void run(Sink sink, String logPath, String oraclePath, int rounds, boolean fatal)
            throws IOException, InterruptedException {
        try (RandomAccessFile file = new RandomAccessFile(logPath, "r")) {
            Scenario scenario = new Scenario(sink, file);
            scenario.rounds(rounds, fatal);
            try (BufferedWriter out = Files.newBufferedWriter(Paths.get(oraclePath), StandardCharsets.UTF_8)) {
                for (String line : scenario.oracle) {
                    out.write(line);
                    out.write('\n');
                }
            }
        }
    }

    private void rounds(int rounds, boolean fatal) throws IOException, InterruptedException {
        for (int number = 1; number <= rounds; number++) {
            for (String level : LEVELS) {
                event(number, level, "plain", "evt " + number + " plain " + level, null);
            }
            if (fatal) {
                event(number, "FATAL", "plain", "evt " + number + " plain FATAL", null);
            }
            event(number, "INFO", "empty", "", null);
            event(number, "INFO", "multiline", "evt " + number + " multiline\n  second line\n\nfourth after a blank", null);
            event(number, "ERROR", "exception", "evt " + number + " exception", chain(number));
            event(number, "WARN", "multiexception", "evt " + number + " multiexception\nsecond line of the message", chain(number));
            event(number, "ERROR", "longmessage", "evt " + number + " longmessage " + "x".repeat(20000), null);
            event(number, "ERROR", "bracket", "evt " + number + " bracket [in] {the} (text) $1 \\d ^ | * + ?",
                    new Exception("first line\nsecond line " + number));
            sink.put("requestId", "req-" + number);
            event(number, "INFO", "mdc", "evt " + number + " mdc", null);
            sink.clear();
            for (String name : new String[] {"worker-" + number, "pool-1-thread-" + number, "My Thread " + number}) {
                final int current = number;
                sink.thread(name, () -> {
                    try {
                        event(current, "INFO", "thread", "evt " + current + " thread " + name, null);
                    } catch (IOException failure) {
                        throw new IllegalStateException(failure);
                    }
                });
            }
        }
    }

    private synchronized void event(int number, String level, String kind, String message, Throwable error)
            throws IOException {
        String before = LocalDateTime.now(ZoneId.systemDefault()).format(STAMP);
        sink.log(level, message, error);
        String after = LocalDateTime.now(ZoneId.systemDefault()).format(STAMP);
        long lines = newLines();
        String first = message.split("\n", -1)[0];
        String thrown = error == null ? "" : error.toString().split("\n", -1)[0];
        oracle.add(String.join("\t", String.valueOf(number), level, kind, first, String.valueOf(lines), before, after, thrown));
    }

    private long newLines() throws IOException {
        long length = file.length();
        byte[] bytes = new byte[(int) (length - offset)];
        file.seek(offset);
        file.readFully(bytes);
        offset = length;
        long lines = 0;
        boolean content = false;
        for (byte one : bytes) {
            if (one == '\n') {
                if (content) {
                    lines++;
                }
                content = false;
            } else if (one != ' ' && one != '\t' && one != '\r') {
                content = true;
            }
        }
        return lines;
    }
}
