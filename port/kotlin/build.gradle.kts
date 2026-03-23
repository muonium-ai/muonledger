plugins {
    kotlin("jvm") version "2.0.0"
    application
}

version = "0.9.0"

repositories {
    mavenCentral()
}

dependencies {
    testImplementation(kotlin("test"))
}

tasks.test {
    useJUnitPlatform()
}

application {
    mainClass.set("muonledger.MainKt")
}
