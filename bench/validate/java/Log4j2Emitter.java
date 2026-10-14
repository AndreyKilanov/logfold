import org.apache.logging.log4j.Level;
import org.apache.logging.log4j.LogManager;
import org.apache.logging.log4j.Logger;
import org.apache.logging.log4j.ThreadContext;

/** Writes the scenario through log4j2; the configuration (file ``log4j2.xml``) is chosen by the caller. */
public final class Log4j2Emitter {
    public static void main(String[] args) throws Exception {
        Logger logger = LogManager.getLogger("com.example.app.service.OrderService");
        Scenario.Sink sink = new Scenario.Sink() {
            public void log(String level, String message, Throwable error) {
                logger.log(Level.toLevel(level), message, error);
            }

            public void put(String key, String value) {
                ThreadContext.put(key, value);
            }

            public void clear() {
                ThreadContext.clearAll();
            }

            public void thread(String name, Runnable work) throws InterruptedException {
                Thread thread = new Thread(work, name);
                thread.start();
                thread.join();
            }
        };
        Scenario.run(sink, args[0], args[1], Integer.parseInt(args[2]), true);
        LogManager.shutdown();
    }
}
