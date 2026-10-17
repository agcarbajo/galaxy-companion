package io.github.agcarbajo.galaxycompanion.dualboot

import android.content.Context
import android.os.Build
import org.json.JSONArray
import org.json.JSONObject

/**
 * What this app needs to know about a device, read from the same JSON
 * profiles Galaxy Companion uses on Linux (`dual_boot` section).
 *
 * The profiles are copied into the APK at build time, so adding a device is
 * adding one file to `packaging/galaxy-companion/usr/share/galaxy-companion/devices`.
 * See docs/dual-boot.md.
 */
data class Profile(
    val id: String,
    val name: String,
    /** The partitions a switch writes; a size of 0 means "whatever the partition is". */
    val partitions: List<Part>,
    /** Written first, and the one whose kernel proves an image is Android's. */
    val kernelPartition: String,
    /** The by-name partition holding Linux's root filesystem. */
    val linuxRoot: String,
    val linuxRootFs: String,
    /** Paths inside Linux's root filesystem. */
    val setsDir: String,
    val backupsDir: String,
    /** `ro.product.device` values this profile is for. */
    val androidDevices: List<String>,
) {
    data class Part(val name: String, val size: Long)

    companion object {
        const val DEFAULT_SETS_DIR = "/var/lib/galaxy-companion/boot-sets"

        /** A profile with dual boot, or null for any other profile. */
        fun parse(text: String): Profile? {
            val json = try { JSONObject(text) } catch (e: Exception) { return null }
            val features = json.optJSONArray("features")?.strings() ?: emptyList()
            val dual = json.optJSONObject("dual_boot") ?: return null
            if ("dual-boot" !in features) return null
            val listed = dual.optJSONArray("partitions") ?: json.optJSONArray("boot_partitions") ?: return null
            val parts = (0 until listed.length()).mapNotNull { i ->
                when (val item = listed.get(i)) {
                    is String -> Part(item, 0)
                    is JSONObject -> item.optString("name").takeIf { it.isNotEmpty() }
                        ?.let { Part(it, item.optLong("size", 0)) }
                    else -> null
                }
            }.filter { it.name.matches(SAFE) }
            val linuxRoot = dual.optString("linux_root")
            if (parts.isEmpty() || !linuxRoot.matches(SAFE)) return null
            val names = parts.map { it.name }
            val setsDir = dual.optString("sets_dir").ifEmpty { DEFAULT_SETS_DIR }
            val paths = listOf(setsDir, dual.optString("backups_dir").ifEmpty { setsDir.trimEnd('/') + "-backups" })
            if (paths.any { !it.matches(PATH) }) return null
            return Profile(
                id = json.optString("id"),
                name = json.optString("name"),
                partitions = parts,
                kernelPartition = dual.optString("kernel_partition").takeIf { it in names }
                    ?: if ("boot" in names) "boot" else names.first(),
                linuxRoot = linuxRoot,
                linuxRootFs = dual.optString("linux_root_fs").ifEmpty { "ext4" }
                    .takeIf { it.matches(SAFE) } ?: "ext4",
                setsDir = paths[0],
                backupsDir = paths[1],
                androidDevices = dual.optJSONArray("android_devices")?.strings() ?: emptyList(),
            )
        }

        /** The profile naming one of [devices] (`ro.product.device` and friends). */
        fun match(profiles: List<Profile>, devices: List<String>): Profile? =
            profiles.firstOrNull { profile -> profile.androidDevices.any { it in devices } }

        @Volatile
        private var loaded: Profile? = null

        @Volatile
        private var looked = false

        /** This device's profile, read once per process. */
        fun current(context: Context): Profile? {
            if (!looked) synchronized(this) {
                if (!looked) {
                    val assets = context.applicationContext.assets
                    val profiles = (assets.list("devices") ?: emptyArray())
                        .filter { it.endsWith(".json") }
                        .mapNotNull { name ->
                            parse(assets.open("devices/$name").bufferedReader().use { it.readText() })
                        }
                    loaded = match(profiles, listOf(Build.DEVICE, Build.PRODUCT))
                    loaded?.let { BootSets.configure(it) }
                    looked = true
                }
            }
            return loaded
        }

        /** Names and paths end up in root shell lines, so they are kept plain. */
        private val SAFE = Regex("[A-Za-z0-9_.-]{1,64}")
        private val PATH = Regex("/[A-Za-z0-9_./-]{1,200}")

        private fun JSONArray.strings(): List<String> = (0 until length()).map { getString(it) }
    }
}
