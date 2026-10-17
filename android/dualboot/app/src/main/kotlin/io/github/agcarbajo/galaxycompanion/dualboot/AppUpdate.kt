package io.github.agcarbajo.galaxycompanion.dualboot

import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInfo
import android.content.pm.PackageInstaller
import android.content.pm.PackageManager
import android.os.Build
import java.io.File
import java.net.URL
import java.security.MessageDigest
import javax.net.ssl.HttpsURLConnection
import org.json.JSONObject

/**
 * Updates of this app, from the same GitHub releases as Galaxy Companion.
 *
 * Each release carries `galaxy-companion-dualboot_<version>.apk` next to the
 * Linux package, and both are listed in its `SHA256SUMS`.  An update is only
 * handed to Android after its hash matches, it is this app's package with a
 * higher version, and it is signed with the same key as the app installed:
 * Android would refuse a different key anyway, but only after the download
 * and with a vaguer message.  Installing goes through PackageInstaller, so
 * Android asks for confirmation the way it does for any app update.
 */
object AppUpdate {
    const val REPOSITORY = "agcarbajo/galaxy-companion"
    private const val API = "https://api.github.com/repos/$REPOSITORY/releases/latest"
    private val ASSET = Regex("galaxy-companion-dualboot_([0-9]+\\.[0-9]+\\.[0-9]+)\\.apk")
    private const val SUMS = "SHA256SUMS"
    const val MAX_APK = 150L * 1024 * 1024
    private const val MAX_METADATA = 1024 * 1024
    private val HEX = Regex("[0-9a-f]{64}")

    data class Release(
        val version: String,
        val apkName: String,
        val apkUrl: String,
        val apkSize: Long,
        val sumsUrl: String,
        val page: String,
    )

    /** Why an update stopped, each with its own message in the app. */
    enum class Failure { NETWORK, NOT_FOUND, CHECKSUM, PACKAGE, SIGNATURE, INSTALL }

    class UpdateException(val failure: Failure, message: String) : Exception(message)

    // -- pure parts, unit tested ---------------------------------------------

    /** The APK of a GitHub release, or null when the release has none. */
    fun parseRelease(json: String): Release? {
        val release = JSONObject(json)
        val assets = release.optJSONArray("assets") ?: return null
        var apk: JSONObject? = null
        var sums: JSONObject? = null
        for (i in 0 until assets.length()) {
            val asset = assets.getJSONObject(i)
            val name = asset.optString("name")
            if (ASSET.matches(name)) apk = asset
            if (name == SUMS) sums = asset
        }
        apk ?: return null
        sums ?: return null
        val name = apk.getString("name")
        val size = apk.optLong("size", -1)
        if (size !in 1..MAX_APK) return null
        val urls = listOf(apk.optString("browser_download_url"), sums.optString("browser_download_url"))
        if (urls.any { !it.startsWith("https://") }) return null
        return Release(ASSET.matchEntire(name)!!.groupValues[1], name, urls[0], size, urls[1],
            release.optString("html_url"))
    }

    /** The hash `SHA256SUMS` gives for [name], or null. */
    fun parseSums(text: String, name: String): String? = text.lineSequence()
        .map { it.trim().split(Regex("\\s+\\*?"), limit = 2) }
        .firstOrNull { it.size == 2 && it[1] == name && HEX.matches(it[0]) }?.get(0)

    /**
     * The versionCode build.gradle.kts gives [version] (major.minor.patch):
     * 100000 + major * 10000 + minor * 100 + patch, monotonic across the
     * numbering restart at 0.9.0 (the last pre-restart build, 2.3.0, was 20300).
     */
    fun code(version: String): Int {
        val parts = version.substringBefore('-').split('.').map { it.toIntOrNull() ?: 0 }
        return 100000 + parts.getOrElse(0) { 0 } * 10000 + parts.getOrElse(1) { 0 } * 100 + parts.getOrElse(2) { 0 }
    }

    /** Whether release [candidate] would install over the app whose versionCode is [currentCode]. */
    fun newer(candidate: String, currentCode: Int): Boolean = code(candidate) > currentCode

    // -- network ---------------------------------------------------------------

    private fun open(url: String): HttpsURLConnection {
        val connection = URL(url).openConnection() as? HttpsURLConnection
            ?: throw UpdateException(Failure.NETWORK, "only HTTPS is allowed")
        connection.connectTimeout = 20_000
        connection.readTimeout = 60_000
        connection.setRequestProperty("Accept", "application/vnd.github+json")
        connection.setRequestProperty("User-Agent", "GalaxyCompanionDualboot/${BuildConfig.VERSION_NAME}")
        return connection
    }

    private fun readText(url: String): String {
        val connection = open(url)
        try {
            val code = connection.responseCode
            if (code == 404) throw UpdateException(Failure.NOT_FOUND, "no published release")
            if (code !in 200..299) throw UpdateException(Failure.NETWORK, "GitHub answered $code")
            val bytes = connection.inputStream.use { it.readNBytesCompat(MAX_METADATA + 1) }
            if (bytes.size > MAX_METADATA) throw UpdateException(Failure.NETWORK, "answer too large")
            return String(bytes, Charsets.UTF_8)
        } catch (e: java.io.IOException) {
            throw UpdateException(Failure.NETWORK, e.message ?: "network error")
        } finally {
            connection.disconnect()
        }
    }

    private fun java.io.InputStream.readNBytesCompat(limit: Int): ByteArray {
        val out = java.io.ByteArrayOutputStream()
        val buffer = ByteArray(64 * 1024)
        while (out.size() < limit) {
            val n = read(buffer, 0, minOf(buffer.size, limit - out.size()))
            if (n < 0) break
            out.write(buffer, 0, n)
        }
        return out.toByteArray()
    }

    /** The newest release with an APK, if it is newer than this app. */
    fun check(): Release? {
        val release = parseRelease(readText(API)) ?: return null
        return release.takeIf { newer(it.version, BuildConfig.VERSION_CODE) }
    }

    private fun updatesDir(context: Context) = File(context.cacheDir, "updates").apply { mkdirs() }

    /** Downloads and checks an update; [progress] gets 0..100. */
    fun download(context: Context, release: Release, progress: (Int) -> Unit): File {
        val expected = parseSums(readText(release.sumsUrl), release.apkName)
            ?: throw UpdateException(Failure.CHECKSUM, "${release.apkName} is not in $SUMS")
        val dir = updatesDir(context)
        dir.listFiles()?.forEach { it.delete() }
        val file = File(dir, release.apkName)
        val digest = MessageDigest.getInstance("SHA-256")
        val connection = open(release.apkUrl)
        try {
            if (connection.responseCode !in 200..299)
                throw UpdateException(Failure.NETWORK, "GitHub answered ${connection.responseCode}")
            var done = 0L
            connection.inputStream.use { input ->
                file.outputStream().use { output ->
                    val buffer = ByteArray(256 * 1024)
                    while (true) {
                        val n = input.read(buffer)
                        if (n < 0) break
                        done += n
                        if (done > release.apkSize || done > MAX_APK)
                            throw UpdateException(Failure.CHECKSUM, "larger than announced")
                        digest.update(buffer, 0, n)
                        output.write(buffer, 0, n)
                        progress((done * 100 / release.apkSize).toInt())
                    }
                }
            }
        } catch (e: java.io.IOException) {
            file.delete()
            throw UpdateException(Failure.NETWORK, e.message ?: "download failed")
        } finally {
            connection.disconnect()
        }
        val got = digest.digest().joinToString("") { "%02x".format(it) }
        if (got != expected) {
            file.delete()
            throw UpdateException(Failure.CHECKSUM, "sha256 $got, expected $expected")
        }
        verifyPackage(context, file)
        return file
    }

    @Suppress("DEPRECATION")
    private fun signers(info: PackageInfo?): Set<String> =
        info?.signingInfo?.let { signing ->
            (if (signing.hasMultipleSigners()) signing.apkContentsSigners else signing.signingCertificateHistory)
                ?.map { it.toCharsString() }?.toSet()
        } ?: emptySet()

    private fun verifyPackage(context: Context, file: File) {
        val pm = context.packageManager
        val flags = PackageManager.GET_SIGNING_CERTIFICATES
        val candidate = pm.getPackageArchiveInfo(file.path, flags)
        val installed = pm.getPackageInfo(context.packageName, flags)
        if (candidate == null || candidate.packageName != context.packageName ||
            candidate.longVersionCode <= installed.longVersionCode) {
            file.delete()
            throw UpdateException(Failure.PACKAGE, "not a newer build of this app")
        }
        // The installed app's current signer must be among the update's.
        val mine = signers(installed)
        if (mine.isEmpty() || signers(candidate).intersect(mine).isEmpty()) {
            file.delete()
            throw UpdateException(Failure.SIGNATURE, "signed with another key")
        }
    }

    /** Hands a checked APK to Android; [InstallReceiver] hears the outcome. */
    fun install(context: Context, file: File) {
        val installer = context.packageManager.packageInstaller
        val params = PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL).apply {
            setAppPackageName(context.packageName)
            // Updating itself without a prompt is allowed once Android
            // considers this app its own installer; otherwise it asks.
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S)
                setRequireUserAction(PackageInstaller.SessionParams.USER_ACTION_NOT_REQUIRED)
        }
        val id = installer.createSession(params)
        installer.openSession(id).use { session ->
            session.openWrite("update.apk", 0, file.length()).use { out ->
                file.inputStream().use { it.copyTo(out) }
                session.fsync(out)
            }
            val intent = Intent(context, InstallReceiver::class.java)
            val pending = PendingIntent.getBroadcast(context, id, intent,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_MUTABLE)
            session.commit(pending.intentSender)
        }
    }
}
