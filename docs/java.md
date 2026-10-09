# Java / JVM adapter guide (manual, not CLI-supported yet)

For Java projects, prefer **ArchUnit** in your existing JUnit build rather than extending the portable runner to parse bytecode itself.

Example (customize the package prefix and module names):

```java
package org.example.architecture;

import static com.tngtech.archunit.lang.syntax.ArchRuleDefinition.noClasses;

import com.tngtech.archunit.core.importer.ClassFileImporter;
import org.junit.jupiter.api.Test;

public class ArchitectureTest {
    @Test
    void learningMustNotDependOnPublishing() {
        var classes = new ClassFileImporter().importPackages("org.example");
        noClasses().that().resideInAPackage("..learning..")
                .should().dependOnClassesThat().resideInAPackage("..publishing..")
                .check(classes);
    }
}
```

Add ArchUnit to your test dependencies, run the normal Maven/Gradle test task in CI, and keep project-specific boundaries in your Java tests. `aegkit init --language java` is **not** implemented in 0.2. Do not assume the generic CLI enforces JVM contracts.
