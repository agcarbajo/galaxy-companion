package io.github.agcarbajo.galaxycompanion.dualboot

/**
 * Switching systems means replacing the boot partitions the device profile
 * lists: four on a Galaxy Tab S9 Ultra, a single `boot` on other devices.
 *
 * The sets are discovered rather than hardcoded: every directory under the
 * profile's sets directory -- on Linux's own root filesystem, which this app
 * mounts -- that holds one image per partition is a system the device can
 * boot.  Linux saves its set itself every time it boots; this app saves
 * Android's (see [BootMaintenance]).
 *
 * `vbmeta` must never be in the list.  Android runs fine with the unsigned
 * vbmeta Linux needs, and rewriting it invalidates the key Android derives for
 * its encrypted /data, which costs a full wipe of Android's user data.  `super`
 * is not in it either, which is why two Android ROMs cannot both be installed:
 * the pairing that works is Linux against whichever Android is installed.
 */
object BootSets {

    data class Partition(val name: String, val bytes: Long) {
        val device: String get() = "/dev/block/by-name/$name"
    }

    @Volatile
    var profile: Profile? = null
        private set

    /** The profile's partitions with their real sizes, kernel first. */
    @Volatile
    var PARTITIONS: List<Partition> = emptyList()
        private set

    /** Uses [profile]; sizes the profile leaves out are read when root is there. */
    fun configure(profile: Profile) {
        this.profile = profile
        PARTITIONS = ordered(profile, profile.partitions.map { Partition(it.name, it.size) })
    }

    private fun ordered(profile: Profile, parts: List<Partition>) =
        parts.sortedBy { it.name != profile.kernelPartition }

    /**
     * Reads every partition's size, refusing one that is missing or not the
     * size the profile promises: a wrong partition must never be read as a
     * right one.
     */
    fun resolveSizes(): Boolean {
        val profile = profile ?: return false
        val result = Root.run(*PARTITIONS.map { "blockdev --getsize64 ${it.device}" }.toTypedArray())
        val sizes = result.output.lines().mapNotNull { it.trim().toLongOrNull() }
        if (!result.ok || sizes.size != PARTITIONS.size) return false
        val wanted = profile.partitions.associate { it.name to it.size }
        val resolved = PARTITIONS.zip(sizes).map { (part, size) ->
            val promised = wanted[part.name] ?: 0
            if (size <= 0 || (promised > 0 && promised != size)) return false
            Partition(part.name, size)
        }
        PARTITIONS = resolved
        return true
    }

    const val ANDROID = "android"
    const val LINUX = "linux"

    /** One bootable system: a directory of images plus a name to show. */
    data class BootSet(
        val id: String,
        val label: String,
        val complete: Boolean,
        val hashes: Map<String, String>,
        /** Where its images actually live; may be on the read-only Linux mount. */
        val dir: String,
        /** linux or android, from the set's `kind` file or guessed from its id. */
        val kind: String = kindFromId(id),
    ) {
        fun file(part: Partition): String = "$dir/${part.name}.img"
    }

    /**
     * Where a set can live.
     *
     * Linux's root filesystem holds them all, at the profile's `sets_dir`:
     * that is where Linux saves its own set and where it reads Android's, so
     * nothing is ever copied twice.  `/sdcard/BootSets` stays as the place to
     * add or override one by hand.
     */
    const val ROOT_DIR = "/sdcard/BootSets"
    const val LINUX_MOUNT = "/mnt/galaxy-companion-linux"

    val linuxSets: String get() = LINUX_MOUNT + (profile?.setsDir ?: Profile.DEFAULT_SETS_DIR)
    val linuxBackups: String get() = LINUX_MOUNT + (profile?.backupsDir ?: (Profile.DEFAULT_SETS_DIR + "-backups"))

    private val LINUX_WORDS = listOf("linux", "ubuntu", "debian", "fedora", "arch", "postmarket", "mobian")

    fun kindFromId(id: String): String =
        if (LINUX_WORDS.any { id.lowercase().contains(it) }) LINUX else ANDROID

    /**
     * Mounts Linux's root read-only, if it is not mounted already.
     *
     * Discovery stays read-only. BootMaintenance briefly remounts it writable
     * only for a verified backup transaction. A plain `ro` mount still replays
     * an ext4 journal, which fails on a filesystem left dirty by a hard
     * power-off, so `noload` is the fallback -- it skips recovery and reads
     * what is there.
     */
    fun mountLinuxRoot(): Boolean {
        val profile = profile ?: return false
        val node = "/dev/block/by-name/${profile.linuxRoot}"
        val fs = profile.linuxRootFs
        val fallback = if (fs == "ext4") " || mount -o ro,noload -t ext4 $node $LINUX_MOUNT" else ""
        val result = Root.run(
            "[ -b $node ] || [ -e $node ]",
            "mkdir -p $LINUX_MOUNT",
            "if grep -q ' $LINUX_MOUNT ' /proc/mounts; then exit 0; fi",
            "mount -o ro -t $fs $node $LINUX_MOUNT 2>/dev/null$fallback",
        )
        return result.ok
    }

    /**
     * Last-resort names, deliberately without version numbers.
     *
     * A real name comes from `name.txt`, stamped by whichever system is
     * running -- see [runningSystemName].  Guessing a version here is how a
     * tablet on One UI 7 ends up being told it runs One UI 8.
     */
    private val KNOWN_LABELS = mapOf(
        "ubuntu" to "Ubuntu",
        "linux" to "Linux",
        "android" to "Android",
        "oneui" to "Android",
        "lineage" to "LineageOS",
        "lineageos" to "LineageOS",
    )

    /**
     * What the system running right now calls itself.
     *
     * One UI encodes its version as major*10000 + minor*100 + patch, so 80000
     * is 8.0.  LineageOS publishes its own property.  Anything else falls back
     * to the Android release number, which is always there.
     */
    fun runningSystemName(): String {
        fun prop(name: String): String =
            Root.run("getprop $name").output.trim().takeIf { it.isNotEmpty() } ?: ""

        prop("ro.lineage.display.version").takeIf { it.isNotEmpty() }?.let {
            return "LineageOS $it"
        }
        prop("ro.lineage.version").takeIf { it.isNotEmpty() }?.let {
            return "LineageOS $it"
        }

        val release = prop("ro.build.version.release").ifEmpty { "?" }
        val oneui = prop("ro.build.version.oneui").toIntOrNull()
        if (oneui != null && oneui > 0) {
            val major = oneui / 10000
            val minor = (oneui % 10000) / 100
            return if (minor == 0) "One UI $major" else "One UI $major.$minor"
        }
        return "Android $release"
    }

    // -- reading -------------------------------------------------------------

    /** Whether a set is the Linux side: only for its icon and who names it. */
    fun isLinux(set: BootSet): Boolean = set.kind == LINUX

    /** sha256 of every boot partition as the device holds it right now. */
    fun liveHashes(): Map<String, String> {
        if (PARTITIONS.isEmpty() || !resolveSizes()) return emptyMap()
        val result = Root.run(*PARTITIONS.map { "sha256sum ${it.device}" }.toTypedArray())
        if (!result.ok) return emptyMap()
        return parseSums(result.output, PARTITIONS.map { it.device })
    }

    /**
     * Every set the device can see, from either place.
     *
     * Linux's copy is read first and Android's own second, so a directory
     * placed by hand in `/sdcard/BootSets` wins over the saved one: that is
     * the only copy the owner can actually edit from here.
     */
    fun discover(): List<BootSet> {
        if (profile == null) return emptyList()
        mountLinuxRoot()
        resolveSizes()

        val where = LinkedHashMap<String, String>()
        for (base in listOf(linuxSets, ROOT_DIR)) {
            Root.run("ls -1 $base 2>/dev/null || true").output.lineSequence()
                .map { it.trim() }
                .filter { it.matches(Regex("[A-Za-z0-9_-]{1,40}")) }
                .forEach { where[it] = base }
        }

        return where.keys.sorted().map { id ->
            val dir = "${where[id]}/$id"
            val fallback = KNOWN_LABELS[id.lowercase()] ?: id.replaceFirstChar { it.uppercase() }
            val hashes = hashesOf(dir)
            BootSet(
                id = id,
                label = readLine(dir, "name.txt")?.takeIf { it.length <= 40 } ?: fallback,
                complete = hashes.size == PARTITIONS.size && hashes.isNotEmpty(),
                hashes = hashes,
                dir = dir,
                kind = readLine(dir, "kind")?.takeIf { it == LINUX || it == ANDROID } ?: kindFromId(id),
            )
        }
    }

    private fun readLine(dir: String, name: String): String? {
        val r = Root.run("cat \"$dir/$name\" 2>/dev/null || true")
        return r.output.lineSequence().firstOrNull()?.trim()?.takeIf { it.isNotEmpty() }
    }

    /**
     * sha256 of a stored set, or an empty map when the set is incomplete.
     *
     * A missing or short file has to be caught here, before anything is
     * written: half a set on disk would otherwise become half a set on the
     * partitions, and the device would boot no system at all.
     */
    private fun hashesOf(dir: String): Map<String, String> {
        val files = PARTITIONS.map { "$dir/${it.name}.img" }
        val checks = PARTITIONS.map { part ->
            val f = "$dir/${part.name}.img"
            "[ -f \"$f\" ] || exit 1\n" +
                "[ \"\$(stat -c %s \"$f\")\" = \"${part.bytes}\" ] || exit 1"
        }
        val result = Root.run(*(checks + files.map { "sha256sum \"$it\"" }).toTypedArray())
        if (!result.ok) return emptyMap()
        return parseSums(result.output, files)
    }

    /** Which stored set the live partitions correspond to, if any. */
    fun identify(live: Map<String, String>, sets: List<BootSet>): BootSet? {
        if (live.size != PARTITIONS.size || live.isEmpty()) return null
        return sets.firstOrNull { set ->
            set.complete && PARTITIONS.all { part ->
                val here = live[part.device]
                here != null && here == set.hashes[set.file(part)]
            }
        }
    }

    /**
     * What to do with Android's saved set, given what the partitions hold.
     *
     * CREATE: there is none yet -- the first run after Linux was installed.
     * CHANGED: Android was updated (or rooted) and its images differ.
     * LINUX_STAGED: Linux is written and waits for a restart; leave Android's.
     * MIXED: some partitions are Linux's and some are not, a switch that
     * stopped half way; nothing may be saved from that.
     */
    enum class BackupDecision { UNCHANGED, CHANGED, CREATE, LINUX_STAGED, MIXED, AMBIGUOUS }

    fun backupDecision(sets: List<BootSet>, live: Map<String, String>): BackupDecision {
        if (live.size != PARTITIONS.size || live.isEmpty()) return BackupDecision.AMBIGUOUS
        val androids = sets.filterNot { isLinux(it) }
        if (androids.size > 1) return BackupDecision.AMBIGUOUS
        val android = androids.singleOrNull()
        val next = identify(live, sets)
        if (next != null && isLinux(next)) return if (android?.complete == true)
            BackupDecision.LINUX_STAGED else BackupDecision.AMBIGUOUS
        if (sets.filter { isLinux(it) }.any { linux ->
                PARTITIONS.any { part ->
                    live[part.device] == linux.hashes[linux.file(part)] &&
                        (android == null || live[part.device] != android.hashes[android.file(part)])
                }
            }) return BackupDecision.MIXED
        if (android == null) return BackupDecision.CREATE
        return if (next?.id == android.id) BackupDecision.UNCHANGED else BackupDecision.CHANGED
    }

    fun runningAndroid(sets: List<BootSet>, name: String): BootSet? {
        val android = sets.filterNot { isLinux(it) }
        return (android.singleOrNull() ?: android.firstOrNull { it.label == name })?.copy(label = name)
    }

    // -- storage -------------------------------------------------------------

    data class Share(val total: Long, val used: Long, val known: Boolean)

    /** How the internal storage is split between the two systems. */
    fun storage(): Map<String, Share> {
        val out = mutableMapOf<String, Share>()
        // Android's df is toybox: it has no -B, and reports 1K blocks.
        fun df(path: String): Share? {
            val cols = Root.run("df -k $path | tail -1").output.trim().split(Regex("\\s+"))
            val total = cols.getOrNull(1)?.toLongOrNull() ?: return null
            val used = cols.getOrNull(2)?.toLongOrNull() ?: return null
            return if (total > 0) Share(total * 1024, used * 1024, known = true) else null
        }
        df("/data")?.let { out[ANDROID] = it }
        // Linux's root is mounted for discovery, so its own usage is readable.
        if (mountLinuxRoot()) df(LINUX_MOUNT)?.let { out[LINUX] = it }
        return out
    }

    // -- writing -------------------------------------------------------------

    /**
     * Progress is reported as partitions, not as sentences.
     *
     * The set of partitions is known before anything starts, so the UI can draw
     * all of them up front and light them up one by one instead of growing a
     * list of lines.  Messages carry string resource ids because this object
     * has no Context and the app is translated.
     */
    sealed interface Progress {
        data class Writing(val part: String) : Progress
        data class Verified(val part: String) : Progress
        data class Failed(val text: Int, val arg: String = "", val detail: String = "") : Progress
        data object Done : Progress
    }

    /**
     * Writes one set, verifying every partition by reading it back.
     *
     * Nothing reboots here.  A caller that has seen [Progress.Failed] must be
     * able to stop, because a device with some partitions replaced still runs
     * the system it is on -- but only until it is restarted.  The kernel goes
     * first, so a switch cut short never leaves this system's kernel in front
     * of the other's images.
     */
    @Synchronized
    fun write(set: BootSet, log: (Progress) -> Unit): Boolean {
        if (!BootMaintenance.beforeSwitch()) {
            log(Progress.Failed(R.string.progress_backup_failed, set.label))
            return false
        }
        val fresh = discover().firstOrNull { it.id == set.id }
        if (fresh == null || !fresh.complete || fresh.hashes != set.hashes || !set.complete) {
            log(Progress.Failed(R.string.progress_incomplete, set.label))
            return false
        }

        for (part in PARTITIONS) {
            val file = set.file(part)
            val expected = set.hashes[file]
            log(Progress.Writing(part.name))

            val write = Root.run("dd if=\"$file\" of=\"${part.device}\" bs=4M", "sync")
            if (!write.ok) {
                log(Progress.Failed(R.string.progress_write_failed, part.name, write.output.take(200)))
                return false
            }

            val got = parseSums(Root.run("sha256sum ${part.device}").output, listOf(part.device))[part.device]
            if (got == null || got != expected) {
                log(Progress.Failed(R.string.progress_mismatch, part.name))
                return false
            }
            log(Progress.Verified(part.name))
        }

        log(Progress.Done)
        return true
    }

    fun reboot() {
        Root.run("sync", "svc power reboot || reboot")
    }

    // -- helpers -------------------------------------------------------------

    /**
     * `sha256sum` prints "<hash>  <path>", and busybox and toybox disagree on
     * the spacing, so the path is matched rather than the column.
     */
    private fun parseSums(output: String, paths: List<String>): Map<String, String> {
        val out = mutableMapOf<String, String>()
        output.lineSequence().forEach { line ->
            val trimmed = line.trim()
            val hash = trimmed.substringBefore(' ').trim()
            if (hash.length != 64) return@forEach
            val path = paths.firstOrNull { trimmed.endsWith(it) }
            if (path != null) out[path] = hash
        }
        return out
    }
}
