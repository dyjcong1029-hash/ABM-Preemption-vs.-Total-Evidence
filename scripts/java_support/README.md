# Process-local Java preferences

`WorkspacePreferencesFactory` replaces Java preferences with an in-memory store
for each headless process. It neither reads nor writes the Windows registry and
does not modify NetLogo GUI preferences. Preferences disappear when the process
exits. It is selected with the JVM property
`-Djava.util.prefs.PreferencesFactory=WorkspacePreferencesFactory`.

The source and both compiled classes are included. The classes use Java class
format 61 (Java 17) and load under the Java 21 runtime bundled with NetLogo 7.0.3.
To rebuild them with a JDK, from this directory run:

```text
javac --release 17 WorkspacePreferencesFactory.java
```

`run_netlogo.py` adds this directory to the classpath and hashes the source and
both class files in each run receipt. It uses a normal Java executable where
available; on Windows installations containing only runtime DLLs it invokes
`JLI_Launch` in a separate Python child process. Each invocation starts a fresh
JVM. Native CSV output must pass the checked run grid, completion and invariant
checks before the run is marked as passed.
