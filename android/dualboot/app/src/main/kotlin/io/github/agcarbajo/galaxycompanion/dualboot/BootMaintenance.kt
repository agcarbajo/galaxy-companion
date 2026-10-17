package io.github.agcarbajo.galaxycompanion.dualboot

import android.content.Context
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Keeps Android's saved set equal to the Android that is installed.
 *
 * The first time this app runs after Linux was installed there is no Android
 * set at all, and it is created; after an Android update (or Magisk patching
 * the boot image) the images differ, and it is replaced.  Either way the live
 * kernel must be the one running ([KernelCheck]) and no partition may be
 * Linux's, so nothing but Android is ever saved as Android.  The copy goes to
 * Linux's root filesystem, where Linux reads it from.  Serialized with
 * discovery and writes.
 */
object BootMaintenance {
    private var context: Context? = null
    private fun quote(value: String) = "'" + value.replace("'", "'\\''") + "'"

    fun log(context: Context): String = context.getSharedPreferences("maintenance", 0)
        .getString("log", "") ?: ""

    private fun record(context: Context, message: String) {
        val time = SimpleDateFormat("MM-dd HH:mm:ss", Locale.ROOT).format(Date())
        context.getSharedPreferences("maintenance", 0).edit()
            .putString("log", (log(context) + "\n$time $message").takeLast(6000)).commit()
    }

    fun recoverInterrupted() {
        if (!BootSets.mountLinuxRoot()) return
        Root.run("""
            m=${BootSets.LINUX_MOUNT}
            b=${BootSets.linuxBackups}
            for previous in "${'$'}b"/*.previous; do
                [ -d "${'$'}previous" ] || continue
                id=${'$'}{previous##*/}; id=${'$'}{id%.previous}
                case "${'$'}id" in ''|*[!a-zA-Z0-9_-]*) continue;; esac
                target=${BootSets.linuxSets}/${'$'}id
                [ ! -e "${'$'}target" ] || continue
                if grep " ${'$'}m " /proc/mounts | grep -q noload; then exit 1; fi
                mount -o remount,rw "${'$'}m"
                trap 'sync; mount -o remount,ro "${'$'}m"' EXIT
                mv "${'$'}previous" "${'$'}target"
                sync
            done
        """.trimIndent())
    }

    fun beforeSwitch(): Boolean {
        val ctx = context ?: return false
        return refresh(ctx, BootSets.discover(), BootSets.liveHashes())
    }

    fun refresh(ctx: Context, sets: List<BootSets.BootSet>, live: Map<String, String>): Boolean {
        context = ctx.applicationContext
        val profile = BootSets.profile ?: return false
        if (!BootSets.mountLinuxRoot()) {
            record(ctx, "Android: Linux's root (${profile.linuxRoot}) cannot be mounted; nothing saved.")
            return false
        }
        val android = sets.filterNot { BootSets.isLinux(it) }.singleOrNull()
        val decision = BootSets.backupDecision(sets, live)
        val next = BootSets.identify(live, sets)
        when (decision) {
            BootSets.BackupDecision.AMBIGUOUS -> {
                record(ctx, "Android: cannot identify a unique Android set or read every partition.")
                return false
            }
            BootSets.BackupDecision.LINUX_STAGED -> {
                record(ctx, "Android: Linux is staged; Android's set preserved.")
                return true
            }
            BootSets.BackupDecision.MIXED -> {
                record(ctx, "Android: the boot partitions are part Linux; nothing saved, switching blocked.")
                return false
            }
            else -> Unit
        }
        if (android != null && (android.dir != "${BootSets.linuxSets}/${android.id}" ||
                !android.id.matches(Regex("[a-zA-Z0-9_-]+")))) {
            record(ctx, "Android: manual set in ${BootSets.ROOT_DIR}; automatic replacement refused.")
            return next?.id == android.id
        }
        val setId = android?.id ?: BootSets.ANDROID
        val name = BootSets.runningSystemName()
        val changed = decision != BootSets.BackupDecision.UNCHANGED
        if (!changed && android?.label == name) {
            record(ctx, "Android: every saved image matches; no copy needed.")
            return true
        }
        if (changed) {
            val release = System.getProperty("os.version").orEmpty()
            val check = KernelCheck.verify(profile.kernelPartition, release, "/data/local/tmp/galaxy-companion-kernel")
            if (!check.ok) {
                record(ctx, "Android: not saved, ${check.detail}.")
                return false
            }
        }
        val expected = BootSets.PARTITIONS.joinToString("\n") {
            "${live.getValue(it.device)}  ${it.name}.img"
        }
        val parts = BootSets.PARTITIONS.joinToString(" ") { "${it.name}:${it.bytes}" }
        val script = ctx.assets.open("refresh-android.sh").bufferedReader().use { it.readText() }
        val result = Root.run(
            "MOUNTPOINT=${quote(BootSets.LINUX_MOUNT)}", "BASE=${quote(BootSets.linuxSets)}",
            "BACKUP=${quote(BootSets.linuxBackups)}", "SET_ID=${quote(setId)}",
            "SYSTEM_NAME=${quote(name)}", "EXPECTED=${quote(expected)}", "PARTS=${quote(parts)}",
            "CHANGED=${if (changed) 1 else 0}", script)
        record(ctx, (if (result.ok) "" else "Android: saving failed (${result.code}).\n") +
            result.output.takeLast(2000))
        if (!result.ok) return false
        Prefs(ctx).clearTileCache()
        return true
    }
}
