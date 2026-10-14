import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.MDC;

/** Writes the scenario through slf4j and logback; the configuration (file ``logback.xml``) is chosen by the caller. */
public final class LogbackEmitter {
    public static void main(String[] args) throws Exception {
        Logger logger = LoggerFactory.getLogger("com.example.app.service.OrderService");
        Scenario.Sink sink = new Scenario.Sink() {
            public void log(String level, String message, Throwable error) {
                switch (level) {
                    case "TRACE" -> logger.trace(message, error);
                    case "DEBUG" -> logger.debug(message, error);
                    case "INFO" -> logger.info(message, error);
                    case "WARN" -> logger.warn(message, error);
                    default -> logger.error(message, error);
                }
            }

            public void put(String key, String value) {
                MDC.put(key, value);
            }

            public void clear() {
                MDC.clear();
            }

            public void thread(String name, Runnable work) throws InterruptedException {
                Thread thread = new Thread(work, name);
                thread.start();
                thread.join();
            }
        };
        Scenario.run(sink, args[0], args[1], Integer.parseInt(args[2]), false);
        ((ch.qos.logback.classic.LoggerContext) LoggerFactory.getILoggerFactory()).stop();
    }
}
