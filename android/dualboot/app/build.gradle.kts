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
		versionCode = 200
		versionName = "2.0.0"
	}

	buildTypes {
		release {
			isMinifyEnabled = false
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
