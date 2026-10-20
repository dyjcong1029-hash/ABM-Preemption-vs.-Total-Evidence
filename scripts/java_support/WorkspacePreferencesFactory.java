import java.util.HashMap;
import java.util.Map;
import java.util.prefs.AbstractPreferences;
import java.util.prefs.Preferences;
import java.util.prefs.PreferencesFactory;

/**
 * Process-local preferences for sandboxed headless runs.
 * Does not read/write the Windows registry or change NetLogo GUI preferences.
 */
public final class WorkspacePreferencesFactory implements PreferencesFactory {
    private final Preferences root = new MemoryPreferences(null, "");
    public Preferences userRoot() { return root; }
    public Preferences systemRoot() { return root; }

    private static final class MemoryPreferences extends AbstractPreferences {
        private final Map<String, String> values = new HashMap<>();
        private final Map<String, MemoryPreferences> children = new HashMap<>();
        MemoryPreferences(AbstractPreferences parent, String name) { super(parent, name); }
        protected void putSpi(String key, String value) { values.put(key, value); }
        protected String getSpi(String key) { return values.get(key); }
        protected void removeSpi(String key) { values.remove(key); }
        protected void removeNodeSpi() { values.clear(); children.clear(); }
        protected String[] keysSpi() { return values.keySet().toArray(new String[0]); }
        protected String[] childrenNamesSpi() { return children.keySet().toArray(new String[0]); }
        protected AbstractPreferences childSpi(String name) {
            return children.computeIfAbsent(name, n -> new MemoryPreferences(this, n));
        }
        protected void syncSpi() {}
        protected void flushSpi() {}
    }
}
