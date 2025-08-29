# poaf

A pretty OK archive format.

Born of a frustration with ZIP and TAR, this format is an attempt to make something better from scratch in 2025.
I've found that WinRAR and 7-Zip have both made archive formats with sounder design and richer feature sets than ZIP and TAR,
but what I'm aiming for is to make a format that is simple enough to convince people to actually adopt it.
Shoutouts to this guy who thought that the ZIP file format was "simple and well-specified": https://github.com/golang/go/issues/24057#issuecomment-377430635 .
This archive format is for you.

Features:
* Friendly to streaming writing
* Inline metadata for streaming reading
* Consolidated metadata at the end for listing
* DEFLATE compression for metadata and contents, optionally split strategically to allow random access
* Redundancy for error detection (not error correction) for every bit of data, mostly CRC32 checksums
* UTF-8 for all strings
* Implicit ancestor directories and explicit empty directories
* Symlinks and POSIX executable bit
* Some limitations on file names to accommodate Windows
* Open specification and permissive licensing

Non-features:
* No support for compression algorithms beyond DEFLATE
* No support for checksums beyond CRC32
* No support for encryption
* No support for file metadata for backup/restore (timestamps, uig/gid, ACLs, etc.)
* No support for obscure file types (block devices, hard links, etc.)
* An archive containing duplicate file names is technically a valid archive, but trying to use it will probably result in an error.
* Windows reserved file names are allowed (CON, NUL, etc.), which also might result in errors.
* This archive format is not extensible; this isn't version 1.0; this is the only version that will ever exist, although this documentation may receive minor updates.

This document is a formal specification for the archive format.
This project also contains example implementations,
but the implementations are informative only; this document is the normative authority.

Here is a non-normative diagram of an archive file:

```
ArchiveHeader // 4 byte signature
compressed {
    // Data Region
    for each item {
        streaming_signature  // 2 byte signature
        file_type
        file_name
        (optional split in compression stream)
        for each chunk of up to 0xffff bytes of item.contents {
            chunk_size
            chunk
        }
        CRC32 of this item's metadata and contents
    }
}
compressed {
    // Index Region
    for each item {
        jump_location // location of the first chunk_size of this item, if there's a split in the compression stream
        file_size
        contents_crc32
        file_type
        file_name
    }
}
ArchiveFooter // location and CRC32 of the Index Region
```

## General Design Discussion

This format is designed to be written once in a single-pass stream, and then read either as a stream or by random access.
Random-access reading means starting with a consolidated metadata index at the end of the archive, then seeking back to selectively read individual items contents as needed.
Streaming reading means reading the entire archive from start to finish, optionally exiting once the consolidated metadata index at the end has been reached.
It's also possible for a streaming reader to validate the index against the data that has been found thusfar.

This format performs compression with the DEFLATE algorithm, the same as ZIP, gzip, PNG, etc.
Metadata and contents from multiple items can be combined into a single compression stream,
resulting in compression ratios comparable to `.tar.gz` archives.
However, the writer can strategically place breaks in the compression stream to support selective reading by random access.
This gives the best of both worlds for large items and small items.

Note that the DEFLATE compression algorithm includes encoding the end of its stream.
This is significant for parsing the structure of this archive format.

There is no support for compression algorithms beyond DEFLATE.
This archive format prioritizes ease of implementation over optimizing compression ratios,
and DEFLATE was chosen because it is the most widely implemented lossless compression algorithm in the world as of 2025;
nearly every programming language standard library supports DEFLATE compression.

This format includes CRC32 checksums (also widely implemented in standard libraries) to guard against subtle and accidental corruption.
Every byte of data in an archive is included in some redundancy check.
File names, types, and contents are hashed with CRC32, and the remaining variable bits in the `ArchiveFooter` are covered by a bespoke checksum.

Note that to guard against malicious corruption, an external cryptographically secure checksum should be used on the entire archive,
which is out of scope for this specification.

There is no support for encryption; that must be done external to this archive format.
Note that the only technical advantage of having encryption built into an archive format is to support selectively reading individual items from an archive encrypted at rest.
If you always want to read the entire archive while decrypting, then the streaming reading use case works nicely within an external encryption layer.
(Note that it is generally not recommended to encrypt the contents of files before archiving them;
not only does that make compression impossible at the archive level (you could compress before encrypting I suppose.),
but it leaves archive metadata unencrypted, which is a dubious combination of secure and insecure use cases;
encrypt at your own risk.)

Use cases that involve making incremental modifications to an existing archive file, such as appending an item, are out of scope;
consider using a database or file system rather than an archive for those use cases.
While the use case of writing an archive to a stream with just-in-time inputs is well supported,
there is no simple way to resume writing an archive from an unexpected interruption, such as the writer crashing.

This format supports symlinks and the posix executable bit because those features are generally useful.
They are supported by git version control, and are frequently used to convey useful information when distributing a collection of files.

This format does not support high resolution file system metadata.
The last-modified timestamp has niche uses, but is more frequently in 2025 a nuisance to determinism.
Fully specifying 9 posix permission bits instead of 1 allows users to encode permissions that are inappropriate in a portable archive.
The distinction between user, group, and global permissions is largely up to the end user, not the author of an archive.
The only important information in an archive is whether a file is executable or not, similar to SVN's `svn:executable` property.
It is inappropriate for directories or symlinks in an archive to specify permission bits.

This format is not extensible.
After using TAR and ZIP for more than 3 decades, humanity can be pretty sure that what we need is an archive format that bundles multiple files together for transport through time and/or space.
We do not need an archive format for backup/restore functionality; software suites for backup/restore use specialized formats, protocols, servers, clients, delta compression, etc. all beyond what any general-purpose archive format can accomplish.
While ZIP's original design planned for future operating system use cases by allowing extensible third-party metadata,
operating systems are out of scope for poaf's design; poaf encodes portable data.
ZIP and TAR were invented before DEFLATE and UTF-8, and so extensibility was wise then, but innovation has plateaued in those spaces;
innovation is mostly done, or at least good enough that we can stop planning for the future.
DEFLATE is not the best compression method, but it's pretty ok.
UTF-8 is the clear dominant winner of the character encoding madness that ended around 2010.
poaf's design is based in a belief that we're basically done innovating in the archive format space.
It's time to lock down one format that works well enough and is easy to implement everywhere.

## Terminology

An **archive** is a file containing 0 or more items.
The items are the primary payload of the archive.
For example, an archive containing items named `README.md` and `LICENSE.md` would be typical for archiving a software project.
The contents of these items would be the text of the documents.

An **item** has a file name, a file type, and an item contents.
A **file name** is a UTF-8 encoded string of bytes; see also the dedicated documentation on `file_name`.
An **item contents** is a sequence of bytes.
A **byte** is 8 bits.

A **file type** is an integer with one of the following values. See also the dedicated documentation on `file_type`:
* `0` - normal file
* `1` - POSIX executable file
* `2` - empty directory
* `3` - symlink

A **file** is a sequence of bytes that can be accessed in some combination of reading and writing either random-access or streaming-only.
The details of accessing a file are beyond the scope of the normative portion of this specification,
however see the Algorithmic Complexity section for some discussion regarding tempfiles.

In addition to the terms defined above, this specification also refers to the following terms defined beyond the scope of this document:
**CRC32**, **DEFLATE**, **UTF-8**.
See References at the end of this document for links to these definitions.

## Spec

All integers are unsigned and in little-endian byte order, meaning the integer 0x12345678 is encoded as the bytes 0x78 0x56 0x34 0x12.
The existence, order, and size of every structure and field specified in this specification is normative.
There is never any padding or unused space between specified structures or fields.

There are 4 regions to an archive:

1. `ArchiveHeader`: 4 bytes, not compressed
2. Data Region: Compressed in one or more streams
3. Index Region: Compressed separately in one stream
4. `ArchiveFooter`: 16 bytes, not compressed

An archive can be read starting with the `ArchiveHeader`, then reading through just the Data Region.
Or an archive can be read by starting with the `ArchiveFooter`, then reading the Index Region,
and then any individual item contents can be read by jumping into the Data Region.

An archive can be written from start to finish with each item being processed one at a time.
The length of the each item contents does not need to be known before writing the item contents to the Data Region.
The Index Region can effectively be created in parallel to the Data Region in a tempfile,
then concatenated to the archive once the Data Region is complete.

When reading an archive, it is possible to read just the `ArchiveHeader` and Data Region,
and then predict every remaining byte in the archive (the Index Region and `ArchiveFooter`), after decompression.
Any deviation from such a prediction would be a violation of the spec.

### Regions

#### `ArchiveHeader`

The `ArchiveHeader` is the following 4-byte structure:

```
struct ArchiveHeader = {
    archive_signature:  4 bytes  // Always 0x9FF0F6BE, i.e. 0xBE 0xF6 0xF0 0x9F
}
```

#### Data Region

The Data Region is compressed in one or more distinct streams,
and every byte of the Data Region structures specified below must be included in exactly one compression stream.
If the Data Region is split into multiple compression streams,
the splits must happen at the locations explained below.

The purpose of compression stream splitting is to enable random-access reading to jump into the middle of the Data Region.
It is suggested that a writer supporting this use case split the read stream at the next opportunity after the previous compressed size exceeds a threshold.
Higher thresholds result in better compression ratios, and lower thresholds result in faster random-access reading of single items.
The recommended threshold for general purpose archives is 1MiB.

Note that in some cases, all the Data Region structures together comprise 0 bytes of data,
but the Data Region must still be compressed.

The Data Region contains the following struct for each item:
```
struct DataItem = {
    streaming_signature:  2 bytes   // Always 0xACDC i.e. 0xDC 0xAC
    type_and_name_size:   2 bytes   // (type_and_name_size >> 14) is the file_type
    file_name:  (type_and_name_size & 0x3FFF) bytes   // In UTF-8

    // Compression stream split may be here.

    // Chunked item contents:
    repeated: {
        chunk_size:  2 bytes
        chunk:       chunk_size bytes
    } until (chunk_size < 0xFFFF)

    streaming_crc32:  4 bytes  // of the whole DataItem except for this field.
}
```

While a reader should validate the `streaming_signature` to guard against implementation errors,
note that it is never necessary for parsing the structure of the archive.

The top 2 bits of `type_and_name_size` is the file type as a 2-bit integer.
The lower 14 bits of `type_and_name_size` is the length of `file_name` in bytes.
`file_name` is encoded in UTF-8 and has a maximum length of `16383`.
See the documentation on the `file_name` field below for more information.

The item's contents is the concatenation of each `chunk`.
Before each `chunk` is a 2-byte `chunk_size` giving the length of the chunk in bytes.
If `chunk_size` is the maximum value `0xFFFF`, there is at least one more chunk.
A `chunk_size` less than `0xFFFF` indicates that this is the last `chunk`.
Note that `chunk_size` can be `0`.

`streaming_crc32` is the CRC32 hash of every byte of the `DataItem` up to but not including the `streaming_crc32` field itself.
Note that the hashed contents is always the uncompressed/decompressed contents.
Note also that a `DataItem` can be split between multiple compression streams.

The end of the Data Region is always the end of a compression stream.
This means that the end of a compression stream where a `streaming_signature` would be expected always signals the end of the Data Region.
Note that there can be 0 occurrences of the `DataItem` struct in the Data Region,
but the Data Region always contains at least 1 compression stream.

#### Index Region

All the structures of the Index Region are compressed together in one compression stream.

The Index Region contains the following structure for each item:

```
struct IndexItem = {
    jump_location:       8 bytes       // Can be 0 meaning unspecified
    file_size:           8 bytes
    contents_crc32:      4 bytes
    type_and_name_size:  2 bytes
    file_name:           (type_and_name_size & 0x3FFF) bytes
}
```

The Index Region and Data Region must encode the same sequence of items, same number and order.
The fields present in both structs (`type_and_name_size` and `file_name`)
must exactly match between each `IndexItem` and the corresponding `DataItem`.

`file_size` is the size of the of the item's contents, after decompression, not including `chunk_size` fields.
`contents_crc32` is the CRC32 of the contents of the item, after decompression, not including `chunk_size` fields.
This means that if the item is extracted to a file system, `file_size` and `contents_crc32` can be computed for the extracted file contents.

The `jump_location` field can sometimes enable a reader to jump into the middle of the archive and read the item's contents without needing to read the entire Data Region up to that point.
However, sometimes jumping to a specific item's contents is not possible, in which case the `jump_location` will be 0.
Every non-zero `jump_location` specifies the offset from the start of the archive to a split in the Data Region compression stream contained within the corresponding `DataItem`,
and every split in the Data Region compression stream must be specified by exactly one `jump_location`.

Note that because the structure of the Data Region can be entirely determined by information in the Index Region,
the following pseudocode can be used to determine how to jump to the contents of each item:

```
// Precompute stream_start_offset and skip_bytes for all index items:
let stream_start_offset = 4 // The start of the Data Region
let skip_bytes = 0
for each index_item {
    if index_item.jump_location > 0 {
        stream_start_offset = index_item.jump_location
        skip_bytes = 0
    } else {
        // Skip the corresponding DataItem's fields before the contents.
        skip_bytes += 4 + index_item.name_size
    }
    index_item.stream_start_offset = stream_start_offset
    index_item.skip_bytes = skip_bytes
    // For the next item, skip the file_contents of this item.
    let chunking_overhead = 2 * (floor(index_item.file_size / 0xFFFF) + 1)
    skip_bytes += index_item.file_size + chunking_overhead
    // Also skip the corresponding DataItem's fields after the contents.
    skip_bytes += 4
}

// Jump to a specific item.
let index_item = the item to jump to.
seek to index_item.stream_start_offset in the archive file.
read and decompress until index_item.skip_bytes decompressed bytes have been read.
// What follows in the compression stream is the first chunk_size of the item's contents.
```

The compression stream for the Index Region ends at the end of the last `IndexItem` struct,
and the `ArchiveHeader` begins immediately after the compression stream ends.
If the archive contains no items, the Index Region is a compression stream that contains 0 bytes.

#### `ArchiveFooter`

The `ArchiveFooter` is the following 16-byte struct:

```
struct ArchiveFooter = {
    index_crc32:            4 bytes
    index_location:         8 bytes
    footer_checksum:        1 byte
    footer_signature:       3 bytes  // Always 0xCFE9EE i.e. 0xEE 0xE9 0xCF
}
```

The archive file must end at the end of the `ArchiveFooter`.
There is never overlap between the `ArchiveFooter` and `ArchiveHeader`,
and because the minimum size of each of the two compressed streams for the Data Region and Index Region are 2,
this means that the offset of the `ArchiveFooter` is always at least 8, and the total size of an archive is always at least 24.
Readers are encouraged to verify `footer_signature` to guard against corruption due to archive truncation.

`footer_checksum` is the lower 8 bits of the sum of each individual byte of `index_location`.
For example if `index_location` is `123456`, then `footer_checksum` is `35`.

`index_location` is the offset in the archive of the start of the compression stream that contains the Index Region.
`index_location` is always at least 6 and always less than the offset of the `ArchiveFooter`.

`index_crc32` is the CRC32 of the entire Index Region, after decompression.

### `file_name`

There are some restrictions placed on `file_name` fields to mitigate compatibility issues with some environments.
However note that readers must be prepared to check for and handle problems beyond what this specification mitigates.
Notably, duplicate file names are not inherently forbidden by this archive format,
and collisions between items are possible even when there is no obvious similarity between item names.
A writer should avoid causing name collisions,
but a reader must always guard against collisions in whatever environment the reader is operating in.

Collisions and other problems with writing a file with a given name to a file system can happen in numerous non-obvious circumstances.
On Windows and MacOS, collisions can come from case insensitivity.
On Windows certain file names are reserved such as `con.txt`.
On MacOS, file names are NFD normalized.
On most systems, there is an upper limit on the length of file paths or on file names within a file path.
These issues are beyond the scope of this technical specification,
so a reader should be prepared to check for problems due to these issues.

If items have colliding or otherwise problematic names, a reader must either trust the first matching non-problematic item or reject the archive.
Because the number of items in an archive is unbounded, there is no hard requirement to guard against name collisions for any use case.
However, during the operation of extracting an archive onto a file system, collisions can be detected by using the appropriate system call, for example:
on POSIX, `open()` with `O_CREAT|O_EXCL` flags; on Windows, `CreateFileW()` with the `CREATE_NEW` creation disposition; etc.

A reader may reject an archive for any reason even if not explicitly required by this specification.

Despite the disclaimers above, this specification does impose some restrictions on the `file_name` field to mitigate common and easily avoided compatibility and security issues on some systems.

* the length of `file_name` in bytes must be at least `1` and at most `16383`.
* `file_name` must be valid UTF-8.
* `file_name` must not contain any bytes in the range `0x00` to `0x1f` (control characters) or any of the following byte values: `0x22`, `0x2a`, `0x3a`, `0x3c`, `0x3e`, `0x3f`, `0x5c`, `0x7c` (`"*:<>?\|`).

Byte value `0x2f` (`/`) is the path delimiter.
Let `segments` be the result of splitting `file_name` on `/`.

For each `segment` in `segments`:
* `segment` must not be empty. (Note this forbids leading and trailing `/` as well as any occurrence of `//`.) 
* `segment` must not be `.` or `..` (byte value `0x2e`). (See `file_type` for how symlink targets differ slightly in this rule.)

This forbids non-normalized paths and path traversal vulnerabilities.

When extracting an archive to a file system, before extracting a given item, a reader should perform the following.
For each substring `ancestor` from the start of `file_name` to just before each `/` in `file_name` in order:
* if `ancestor` does not exist in the target location, a reader should create it as a directory;
* if `ancestor` already exists, a reader should require that it is a directory, not a file or a symlink.

### `file_type`

An item's file type is encoded as a 2-bit integer:

* `0` - normal file
* `1` - POSIX executable file
* `2` - empty directory
* `3` - symlink

A reader may reject archives with unsupported file types.

The distinction between type `0` and `1` is that the latter should have its executable bit set on POSIX systems,
in which case readers are encouraged to set `mode |= (mode & 0o444) >> 2` after file creation rather than simply enabling all three executable bits;
this is to respect any `umask` setting that may have limited the permissions lower than `0o644`.
Note that on Windows, executeability is generally determined by file extension, so an `.exe` file may have file type `0`.

A file of type `2` is only necessary to include in an archive if no other item in the archive implies the need for the directory to exist as its ancestor; see `file_name` above.
It is not possible to specify any metadata for a directory, such as permission bits, timestamps, or owner.
This specification does not guarantee any particular ordering of items in an archive,
which means a reader should be prepared to handle an empty directory specified after another item has already created the directory implicitly as an ancestor, which should not be an error.
If `file_type` is `2`, then the item's contents must be 0-length.

A file of type `3` is a POSIX symlink.
The item's contents is the target.
The maximum contents length for a symlink target in this archive format is `4095`;
note however that a target file system may impose a different limit.

This specification places restrictions on symlink targets, similar to restrictions on `file_name`.
All the same restrictions on `file_name` apply to symlink targets, except that `.` and `..` segments are sometimes permitted:
If the entire link target is `.`, it is permitted, otherwise `.` segments are not allowed.
Let `depth` be the number of `/` bytes in the item's `file_name` (not in the link target).
Let `segments` be the result of splitting the link target on `/`.
A segment may be `..` only if every prior segment, if any, is also `..`, and the total number of `..` segments does not exceed `depth`.
This is to allow symlinks targets to stay within an archive while preventing path traversal vulnerabilities.

## Algorithmic Complexity

While the number of items in an archive, the size of the archive, and the size of each item's contents are all unbounded,
the amount of memory strictly required during any writing or reading operation is always bounded.
The computational complexity analysis in this specification (when values are "bounded") considers 16-bit sizes (up to 65535 bytes) to be negligible, and 64-bit sizes (more than 65535 bytes) to be effectively unbounded.
For example, a file name has a length up to 16383 bytes, which effectively requires worst-case constant memory to store and is not a concern,
while an item contents with a length up to 18446744073709551615 bytes effectively requires worst-case infinite memory to store which is never required.

In addition to memory, a tempfile is recommended during the writing process to assist in the creation of the Index Region.
A tempfile is a sequence of bytes with an unbounded required size that is written once in a streaming mode, then read back once in a streaming mode.
The required size of the tempfile scales with the number of items, not any item contents.
The term tempfile is a suggestion hint for implementers, but could be implemented by an in-memory buffer at the implementer's discretion.

## References

**DEFLATE**: a compression algorithm invented by Phil Katz in 1990, standardized in RFC 1951 (1996). All poaf archives use a 32KiB window size. (Note that in a zlib context, it is considered a "raw" stream; no containers/headers. `windowBits=-15`). https://datatracker.ietf.org/doc/html/rfc1951

**CRC32**: The standard cyclic redundancy check supported by most standard libraries. The following are the standard parameters: width=32 poly=0x04c11db7 init=0xffffffff refin=true refout=true xorout=0xffffffff check=0xcbf43926 residue=0xdebb20e3 name="CRC-32/ISO-HDLC". https://reveng.sourceforge.io/crc-catalogue/all.htm#crc.cat.crc-32-iso-hdlc

**UTF-8**: The most popular variable-width encoding for text as bytes. https://datatracker.ietf.org/doc/html/rfc3629


## Rant about the problems with ZIP files

TODO: move to a blog post.

ZIP is perhaps the most problematic archive format in popular use today.
The specification, called APPNOTE, maintained by PKWARE, Inc. is the source of the format's problems.
The specification and file format have numerous serious ambiguities which lead to developer frustration,
bugs that sometimes have security implications, and disagreement over what really counts as "compliant" with the specification.
The following discussion is in reference to APPNOTE version 6.3.10 timestamped Nov 01, 2022.

[APPNOTE.txt](https://pkware.cachefly.net/webdocs/casestudies/APPNOTE.TXT) is an old document that has not been modernized since the early 1980s.
The plain text format could have been a charming stylistic curiosity if it weren't for all the other long-standing problems with the document,
which suggest the 1980s formatting is further evidence of PKWARE's unwillingness to take accountability for the document's quality.

First, some minor complaints.
The use of ISO verbs ("SHALL", "MAY", etc.) is incorrect.
For example, `4.3.8  File data` specifies that file data "SHOULD" be placed after the local file header,
when really that's the only place for it to be, so it needn't have any ISO verb, but "SHALL" would be the appropriate one.
I believe that whoever added the ISO verbs in version 6.3.3 in 2012 thought that "SHOULD" was how you allowed for 0-length file data arguably existing or not existing based on your philosophical beliefs, which is not appropriate for a technical specification.
Other examples include `4.3.14.1`, `4.4.1.4`, `4.7.1`, and probably many more that I'm not going to bother enumerating; try reading the document yourself, and you'll see what I mean.

Another clue about the problems with APPNOTE is that it includes numerous advertisements for PKWARE proprietary technology with contact information for their sales department encouraging the reader to purchase a license.
I understand that businesses have a job to do (literally) that requires earning money, and PKWARE owns the APPNOTE document
(actually, this is legally dubious) and so it makes sense that they would serve their business interests in a document that is probably a major entrypoint for people learning that PKWARE even exists as a company.
My criticism is not with their desire to run a for-profit business; it's with how the maintainers of the document have chosen to spend their time;
they have bothered to include advertisements for proprietary technology without cleaning up the fundamental problems with the format.

And now to talk about the most fundamental problems with the format, which is that both the APPNOTE document and the format itself are ambiguous.
Ambiguity means that the same ZIP file could be read by two different ZIP readers and found to contain completely different contents.
And ambiguity in the specification means that the implementers of both readers could reasonably believe that theirs is the more compliant and correct interpretation.
Ambiguity is a serious problem, not just for bug-free usability, but for security.
If a security scanner finds that an archive contains one set of contents, and then an application finds a different set of contents, you can see how that would lead to problems.
This [actually happened in the Android operating system](https://googlesystem.blogspot.com/2013/07/the-8219321-android-bug.html),
but thankfully the problem was caught by security researchers before any known instances of the exploit affected any end user.
[Here's another long discussion](https://gynvael.coldwind.pl/?id=682) by security researcher Gynvael Coldwind of how structural ambiguities in the ZIP file format can be used to exploit naive reader implementations.

Here are some structural ambiguities in the file format. These are real bad:
* When searching for the eocdr (End of Central Directory Record), do you search backward from a minimum comment length or forward from a maximum comment length? If you find multiple signatures, is that an error, or is one of them authoritative? Can unused data be after the eocdr, which would make searching for the signature unbounded through the whole archive?
* When streaming the archive through a reader, if you encounter general purpose bit 3 and compression method 0, how do you know when the file data has ended? This is explicitly supported by the specification in `4.4.4` with the phrase "newer versions of PKZIP recognize this bit for any compression method". The data descriptor, which apparently exists to solve this problem, is identified by either a signature or a CRC32 of the file data contents, but that can be maliciously inserted into the file data.
* What is the size of the data descriptor? `4.3.9.1` states "For ZIP64(tm) format archives, the compressed and uncompressed sizes are 8 bytes each.", but nowhere is a definitive definition of what a ZIP64 format archive is. ZIP64 is an extension that can be enabled on individual headers and/or at the very end of the central directory. If the central location is what makes an entire archive in ZIP64 format, then the data descriptor is useless for streaming readers, which according to my read of the specification is the entire purpose of the data descriptor. If instead a data descriptor has 8-byte sizes when the corresponding local file header has the ZIP64 extra field, then it means the writer of the archive would either have needed to know the size would exceed 4GiB, thereby defeating the purpose of general purpose bit 3, or pessimistically needed to prepare for that possibility and spend an extra 24 bytes in the local file header writing an effectively empty ZIP64 extra field. Is that pessimism really the recommendation of the specification?
* When checking for ZIP64 format at the end of the central directory, a reader must check for the Zip64 End of Central Directory Locator signature `0x07064b50` 20 bytes before the eocdr. If the signature is found, then it's the start of the Zip64 End of Central Directory Locator structure. If not, then it's probably part of the last central directory header. In Windows archives, this data is part of the NTFS timestamp extra field. This means that files archived with a particular timestamp could corrupt the archive, incorrectly signaling the presence of ZIP64 structures.

Here are some ambiguities in the specification:
* `4.3.6 Overall .ZIP file format:` gives a diagram of a zip file with no allowance for unused space or overlap between structures. This diagram is the most eye-catching first-impression that someone is likely to notice in the document. However, this diagram contradicts other claims made in `4.1.9` stating that a ZIP file may be a self-extracting archive; no discussion is given about the implications of self-extraction capabilities on the structure of the archive, but it means that there must be space at the start of the file that is not included in the archive.
* `4.3.1` states 'A ZIP file MUST have only one "end of central directory record".', but does not elaborate on what that means. This is likely an attempt to resolve ambiguities when searching backwards for the structure, but several critical details are left unspecified, such as whether simply the 4-byte signature is what must occur only once, or whether it must occur only within the last 64k of the archive where an eocdr could reasonably be found, or whether any ambiguity should be resolved by using the last one found, or what. This leads me to believe that whoever added this clause in version 6.3.3 in 2012 did not understand the problem with eocdr search ambiguity.
* `4.3.1` states "Files MAY be added or replaced within a ZIP file, or deleted.", but this is never elaborated on. These operations are irrelevant for a file format specification; they are more applicable to software that operates on archives. One might read into the claim that unused space may be left in various places throughout the format, but that's never explicitly stated, and there are no stated bounds on where the unused space can be. For example, can there be unused space between central director headers? Unused space at the end of extra field records is intentionally inserted by the Android development tool [zipalign](https://developer.android.com/tools/zipalign); is that supposed to be allowed?
* It is unclear whether small values overridden by ZIP64 extended values must be `-1` i.e. `0xFFFF`, `0xFFFFFF`. This happens in sections `4.4.{8,9,13,16,19,20,21,22,23,24}`. Each of these sections states "If an archive is in ZIP64 format and the value in this field is [-1], the size will be in the corresponding [larger] zip64 end of central directory field.". So if a reader encounters an archive in ZIP64 format and a value is not `-1`, should it still be overridden by the ZIP64 values? Are `-1` values necessary to appear before checking for the ZIP64 format (which can cause ambiguity as stated above)?
* Generally nobody cares about multi-disk support, but `4.4.19 number of this disk` is specified wrong. It states that it's the disk number "which contains central directory end record", which is not a phrase used elsewhere and it's not clear whether that refers to the "end of central directory record" or the "zip64 end of central directory record", which can be on different disks. If each field refers to the struct that contains the field, as the name itself suggests, then one doesn't override the other, because they represent different values. Really, the 16-bit "number of this disk" field is overridden by the 32-bit "total number of disks" field, which encodes the same value but plus 1. Good luck implementing support for more than 65535 disks.
* Speaking of unclear names, APPNOTE can't seem to decide on what to call different structures and fields. The terms "directory" and "dir" seem to be used interchangeably to refer to the same thing. The "End of central directory record" contains an "end of central dir signature", and the field "total number of entries in the central directory on this disk" is sometimes referred to as "total number of entries in the central dir on this disk".
* The character encoding for file names and comments was undefined until APPNOTE 6.3.0 in 2006, where the default character encoding is defined to be "IBM Code Page 437". There are two conflicting definitions of this code page for values in the range 1-31. IBM defines the characters to be various dingbats, whereas Unicode defines the characters to be ASCII control characters with the same name. Info-ZIP uses the Unicode definition.

Here are some other minor criticisms of the ZIP file format. If ZIP files weren't so problematic, these would be the comparison points you'd like to see in some kind of concise table.
* Compression and checksums only cover file contents, not file metadata.
* The structure of an archive is so unconstrained that regions of the archive could be encoded out of order or even overlapping one another. This leads to exploits like the [zip bomb technique used by David Fifield](https://www.bamsoftware.com/hacks/zipbomb/) for extreme compression, which can be a security concern.

Simplified Zip:
```
for each item {
    LocalFileHeader(item) // name, size, CRC32
    optionally compressed {
        item.contents
    }
}
for each item {
    CentralDirectoryHeader(item) // name, size, CRC32, location of LocalFileHeader(item)
}
EndOfCentralDirectoryRecord // location of first CentralDirectoryHeader
```

Common Zip:
```
for each item {
    LocalFileHeader(item) // name, sometimes includes sizes
    optionall compressed {
        item.contents
    }
    if didn't include sizes {
        DataDescriptor(item) // sizes, CRC32
    }
}
for each item {
    CentralDirectoryHeader(item) // name, size, CRC32, location of LocalFileHeader(item)
}
if sometimes {
    Zip64EndOfCentralDirectoryRecord // location of first CentralDirectoryHeader
    Zip64EndOfCentralDirectoryLocator // location of Zip64EndOfCentralDirectoryRecord
}
EndOfCentralDirectoryRecord // sometimes location of first CentralDirectoryHeader
```

Full Madness Zip:
```
for each item in unspecified order {
    (optional padding)
    LocalFileHeader(item) // name, sometimes includes sizes
    optionally encrypted {
        optionally compressed {
            item.contents
        }
    }
    if didn't include sizes {
        DataDescriptor(item) // sizes, CRC32
    }
}
if sometimes {
    ArchiveDecryptionHeader
    ArchiveExtraDataRecord
}
(optional padding)
for each item in unspecified order {
    CentralDirectoryHeader(item) // name, size, CRC32, location of LocalFileHeader(item)
}
(optional padding)
if sometimes {
    Zip64EndOfCentralDirectoryRecord // location of first CentralDirectoryHeader
    (optional padding)
    Zip64EndOfCentralDirectoryLocator // location of Zip64EndOfCentralDirectoryRecord
}
EndOfCentralDirectoryRecord // sometimes location of first CentralDirectoryHeader
```

Tar (and also `ar`):
```
for each item {
    Header(item) // name, size
    item.contents
    (alignment padding)
}
```

`.tar.gz`:
```
GzipHeader // timestamp, checksum of header
compressed {
    // Tar
    for each item {
        Header(item) // name, size
        item.contents
        (alignment padding)
    }
}
GzipFooter // CRC32 of tar
```

`.zip` (simplified):
```
for each item {
    Metadata(item) // name, size
    compressed {
        item.contents
    }
}
// Central Directory
for each item {
    Metadata(item) // name, size, location
}
Footer // backpointer to Central Directory
```

`.poaf` (simplified):
```
Header // signature
compressed {
    for each item {
        Metadata(item) // name
        (optional split in compression stream)
        item.contents
    }
}
// Index Region
compressed {
    for each item {
        Metadata(item) // name, size, location
    }
}
Footer // backpointer to Index Region
```
