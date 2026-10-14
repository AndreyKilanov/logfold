import org.apache.log4j.Level;
import org.apache.log4j.LogManager;
import org.apache.log4j.Logger;
import org.apache.log4j.MDC;

/** Writes the scenario through log4j 1.x (reload4j); the configuration is ``log4j.properties``. */
public final class Log4j1Emitter {
    public static void main(String[] args) throws Exception {
        Logger logger = Logger.getLogger("com.example.app.service.OrderService");
        Scenario.Sink sink = new Scenario.Sink() {
            public void log(String level, String message, Throwable error) {
                logger.log(Level.toLevel(level), message, error);
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
        Scenario.run(sink, args[0], args[1], Integer.parseInt(args[2]), true);
        LogManager.shutdown();
    }
}
