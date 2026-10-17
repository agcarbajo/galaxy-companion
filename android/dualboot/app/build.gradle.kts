import java.util.Properties

plugins {
	alias(libs.plugins.android.application)
	alias(libs.plugins.kotlin.android)
	alias(libs.plugins.kotlin.compose)
}

/**
 * The device profiles are the same files Galaxy Companion reads on Linux, so
 * a device gains dual boot on both sides by adding one JSON file.  They are
 * copied into the APK's assets at build time rather than duplicated here.
 */
abstract class CopyProfiles : DefaultTask() {
	@get:InputDirectory
	abstract val source: DirectoryProperty

	@get:OutputDirectory
	abstract val outputDir: DirectoryProperty

	@TaskAction
	fun copy() {
		val out = outputDir.get().asFile.resolve("devices")
		out.deleteRecursively()
		out.mkdirs()
		source.get().asFile.listFiles { file -> file.name.endsWith(".json") }!!.forEach {
			it.copyTo(out.resolve(it.name))
		}
	}
}

val profiles = rootProject.layout.projectDirectory.dir("../../packaging/galaxy-companion/usr/share/galaxy-companion/devices")
val copyProfiles = tasks.register<CopyProfiles>("copyProfiles") {
	source.set(profiles)
	outputDir.set(layout.buildDirectory.dir("generated/profiles"))
}

/**
 * The app is released together with Galaxy Companion and carries its version,
 * read from the one place it is written.  2.3.0 becomes versionCode 20300.
 */
val companionVersion: List<Int> = rootProject.layout.projectDirectory
	.file("../../packaging/galaxy-companion/usr/lib/galaxy-companion/galaxy_companion/__init__.py").asFile.readText()
	.let { Regex("""VERSION = "(\d+)\.(\d+)\.(\d+)"""").find(it)!!.groupValues.drop(1).map(String::toInt) }

/**
 * Release signing, from a properties file outside the repository named by
 * DUALBOOT_SIGNING (storeFile relative to it, storePassword, keyAlias,
 * keyPassword).  Updates only install over a build signed with the same key,
 * so every published APK must come from this key; without it the release
 * build is left unsigned and scripts/publish-release.sh refuses to publish.
 */
val signing: Properties? = System.getenv("DUALBOOT_SIGNING")?.let { path ->
	Properties().apply { File(path).inputStream().use { load(it) } }
		.also { it["storeFile"] = File(path).parentFile.resolve(it.getProperty("storeFile")).path }
}

androidComponents {
	onVariants { variant ->
		variant.sources.assets?.addGeneratedSourceDirectory(copyProfiles, CopyProfiles::outputDir)
	}
}

android {
	namespace = "io.github.agcarbajo.galaxycompanion.dualboot"
	compileSdk = 35

	defaultConfig {
		applicationId = "io.github.agcarbajo.galaxycompanion.dualboot"
		// Android 10: the oldest Android a supported Galaxy still runs.
		minSdk = 29
		targetSdk = 35
		versionCode = companionVersion[0] * 10000 + companionVersion[1] * 100 + companionVersion[2]
		versionName = companionVersion.joinToString(".")
	}

	signingConfigs {
		if (signing != null) create("release") {
			storeFile = File(signing.getProperty("storeFile"))
			storePassword = signing.getProperty("storePassword")
			keyAlias = signing.getProperty("keyAlias")
			keyPassword = signing.getProperty("keyPassword")
		}
	}

	buildTypes {
		release {
			isMinifyEnabled = false
			signingConfig = signingConfigs.findByName("release")
		}
		debug {
			isMinifyEnabled = false
		}
	}

	compileOptions {
		sourceCompatibility = JavaVersion.VERSION_17
		targetCompatibility = JavaVersion.VERSION_17
	}

	kotlinOptions {
		jvmTarget = "17"
	}

	buildFeatures {
		compose = true
		buildConfig = true
	}

	lint {
		// lifecycle 2.8's detector crashes this lint (IncompatibleClassChangeError);
		// the app uses StateFlow, not LiveData, so it checks nothing here.
		disable += "NullSafeMutableLiveData"
	}

	testOptions {
		unitTests.all {
			// The tests read the real profiles from the repository.
			it.systemProperty("profiles.dir", profiles.asFile.absolutePath)
		}
	}
}

dependencies {
	testImplementation("junit:junit:4.13.2")
	// android.jar only carries stubs of org.json; the tests need the real thing.
	testImplementation("org.json:json:20240303")
	implementation(libs.androidx.core.ktx)
	implementation(libs.androidx.lifecycle.runtime.ktx)
	implementation(libs.androidx.lifecycle.runtime.compose)
	implementation(libs.androidx.lifecycle.viewmodel.compose)
	implementation(libs.androidx.activity.compose)
	implementation(platform(libs.androidx.compose.bom))
	implementation(libs.androidx.ui)
	implementation(libs.androidx.ui.graphics)
	implementation(libs.androidx.ui.tooling.preview)
	implementation(libs.androidx.material3)
	implementation(libs.androidx.material.icons.extended)
}
