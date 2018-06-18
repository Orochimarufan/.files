#!/usr/bin/env python3
# (c) 2015-2017 Taeyeon Mori <orochimarufan.x3@gmail.com>
# Anime Import V5

import os
import sys
import re
import logging
import argparse
import collections
import itertools
import functools
import operator


logger = logging.getLogger("AnimeImport")


###############################################################################
## Utilities                                                                 ##
###############################################################################
def cat_to(filename, text):
     with open(filename, "w") as f:
         f.write(text)


def cat_from(filename):
     with open(filename) as f:
         return f.read()


def abspath_from(path, anchor):
    return os.path.normpath(os.path.join(anchor, path)) if not os.path.isabs(path) else path


def transport_path(path, old_anchor, new_anchor):
    """
    :brief: Transport a relative path from one anchor to another
    """
    return os.path.relpath(abspath_from(path, old_anchor), new_anchor)


def make_symlink(target, at, anchor=None):
    """
    :brief: Make a symbolic link
    :param target: The link target
    :param at: The location of the new symlink
    :param anchor: The anchor if <target> is relative. defaults to os.curdir
    This function preserves the absoluteness of <target>, meaning that if you pass in
        an absolute path, the link will be created using that absolute path.
        However, any relative path will be transported to the new link's containing directory.
        That is important if the link isn't created in the cwd because posix symlink() can take
        any value which will be interpreted relative to the directory containing the link.
    """
    if os.path.isabs(target):
        os.symlink(target, at)
    elif os.path.isdir(at):
        os.symlink(transport_path(target, anchor if anchor else os.curdir, at), at)
    else:
        os.symlink(transport_path(target, anchor if anchor else os.curdir, os.path.dirname(at)), at)


def make_symlink_in(target, in_directory, linkname, anchor=None):
    if os.path.isabs(target):
        os.symlink(target, os.path.join(in_directory, linkname))
    else:
        os.symlink(transport_path(target, anchor if anchor else os.curdir, in_directory),
                   os.path.join(in_directory, linkname))


def clean_links(path):
    for f in os.listdir(path):
        if not f.startswith(".") and os.path.islink(os.path.join(path, f)):
            os.unlink(os.path.join(path, f))


def maybe_number(s):
    return int(s) if s.isdigit() else s


def opt_value_str(o):
    # since maybe_number converts them back to numbers, we abuse numbers as bools
    if o == True:
        return "1"
    elif o == False:
        return "0"
    else:
        return str(o)


def natural_sort_key(s, *, _nsre=re.compile(r'(\d+)')):
    return [int(text) if text.isdigit() else text.lower() for text in _nsre.split(s)]


def natural_name_sort_key(f, *, _nsre=re.compile(r'(\d+)')):
    return [int(text) if text.isdigit() else text.lower() for text in _nsre.split(f.name)]


og_symlink = os.symlink

#def symlink(*a):
#    logger.info("SYMLINK %s", a)
#    og_symlink(*a)

#os.symlink = symlink


###############################################################################
## Specials patterns                                                         ##
###############################################################################
class Special:
    """
    Specials format:
        Specials <= Special '\n' Specials | Special
        Special <= Properties '\n' Regexp
        Regexp <= regular expression with optional 'ep' group
        Properties <= Property '|' Properties | Property
        Property <= Name '=' Value
        Name <= python identifier
        Value <= string value without '\n' and '|'
    Valid keys:
        type <= "extern" "special" "opening" "ending" "trailer" "parody" "other"
        name <= Folder name for "extern" type
        offset <= Number to add to the episode number
        epnum <= Force all matched episodes to have this episode number (discouraged. use offset instead)
        first <= start counting episodes here. This only applies if <ep> is NOT matched in the regexp
        subdir <= Specials are located in a subdir of the source
    Regexp:
        Should contain an <ep> group to match the (relative to [offset]) episode/special/ending/etc number
    """
    def __init__(self, properties, pattern):
        self._properties = properties
        self.pattern = pattern

        self.season = 0

        if "type" in properties:
            t = properties["type"].lower()

            if t in ("extern", "episode", "episodes"):
                self.season = 1
                off = 0
            elif t in ("special", "s", "specials"):
                off = 0
            elif t in ("opening", "op", "openings"):
                off = 99
            elif t in ("ending", "ed", "endings"):
                off = 149
            elif t in ("trailer", "t", "trailers"):
                off = 199
            elif t in ("parody", "p", "parodies"):
                off = 299
            elif t in ("other", "o", "others"):
                off = 399
            else:
                off = 499

            self.type_offset = off
        else:
            self.type_offset = 0

        self.is_extern = "name" in properties
        self.is_subdir = "subdir" in properties

        if "$custom" in properties:
            if not callable(properties["$custom"]):
                raise ValueError("$custom Specials must be created from python code and be callable objects")
            self.custom = properties["$custom"]

    def __getattr__(self, name):
        return self._properties[name]

    def __contains__(self, name):
        return name in self._properties

    def source(self):
        return "\n".join(("|".join(map("=".join, self._properties.items())), self.pattern.pattern))

    def match(self, f):
        return self.pattern.search(f)

    def custom(self, m, i):
        return None

    def adjust_episode(self, ep):
        ep += self.type_offset

        if "offset" in self:
            return ep + int(self.offset)
        elif "epnum" in self:
            return int(self.epnum)
        else:
            return ep

    def get_episode(self, match, last):
        if "ep" in self.pattern.groupindex and match.group("ep"):
            # TODO: fix this. When doing it properly it breaks the assumption that ...OP is OP1 while OPn is OPn. It makes OP OPn+1
            return self.adjust_episode(int(match.group("ep")))
            #return self.adjust_episode(int(match.group("ep")))
        elif last == 0:
            return self.adjust_episode(1)
        else:
            return last + 1

    @staticmethod
    def parse_properties(src):
        return dict(map(lambda p: p.split("=", 1), src.split("|")))

    @classmethod
    def parse(cls, props_src, regexp_src):
        return cls(cls.parse_properties(props_src), re.compile(regexp_src))

    @classmethod
    def iterparse(cls, src):
        for a, b in zip(*[iter(src.split("\n"))]*2):
            yield cls.parse(a, b)

    @classmethod
    def simple(cls, type, regexp):
        return cls({"type": type}, re.compile(regexp))


###############################################################################
## The core                                                                  ##
###############################################################################
class Importer:
    # Filenames
    source_fn = ".source"
    master_fn = ".main"
    pattern_fn = ".pattern"
    exclude_fn = ".exclude"
    special_fn = ".specials"
    options_fn = ".options"

    # Defaults
    default_pattern = re.compile(r"[\s_.](?:[Ss](?:eason)?(?P<season>\d+))?[\s_.]*(?:[Ee](?:[Pp]|pisode)?)?[\s_.]?(?P<ep>\d+)(?:\-(?P<untilep>\d+))?([Vv]\d+)?[\s_.]*[\(\[\.]?")
    default_options = {
        "auto_specials": 1,
        "exclude_parts": 1,
        "exclude_playlists": 1,
    }

    auto_specials = [
        Special.simple("Opening", r"[_ ](NC|TV)?OP[ _]?[^\d]"), # FIXME: HACK
        Special.simple("Opening", r"[_ ]((NC|TV)?OP|Opening)[ _]?(?P<ep>\d+)"),
        Special.simple("Ending", r"[_ ](NC|TV)?ED[ _]?[^\d]"), # FIXME: HACK
        Special.simple("Ending", r"[_ ]((NC|TV)?ED|Ending|Closing)[ _]?(?P<ep>\d+)"),
        Special.simple("Special", r"[_ ](Special|OVA|SP)[ _]?(?P<ep>\d+)?[ _]?"),
        # .nfo files
        Special({"$custom": lambda m, i: ("link", i.destination, i.main_name + ".nfo")}, re.compile(r".nfo$"))
    ]

    log_skip = False

    link_template = "{series} S{season:d}E{episode:03d}"
    until_template = "-E{episode:03d}"

    def format_linkname(self, series, season, episode, *, until_ep=None):
        linkname = self.link_template.format(series=series, season=season, episode=episode)
        if until_ep:
            linkname += self.until_template.format(episode=until_ep)
        return linkname

    def __init__(self, destination):
        # Find master
        master_f = os.path.join(destination, self.master_fn)

        while os.path.islink(master_f):
            new_dest = os.readlink(master_f)
            if not os.path.isabs(new_dest):
                new_dest = transport_path(new_dest, destination, os.curdir)

            logger.info("Destination '%s' belongs to '%s'; Selecting that instead" % (destination, new_dest))

            destination = new_dest
            master_f = os.path.join(destination, self.master_fn)

        self.destination = os.path.abspath(destination)
        self.main_name = os.path.basename(self.destination)

        self.library_path = os.path.normpath(os.path.join(self.destination, ".."))

        def get_source_loc(fn):
            source = os.readlink(fn)
            if not os.path.isabs(source):
                source = transport_path(source, os.path.dirname(fn), os.curdir)
            return source

        source_f = os.path.join(destination, self.source_fn)
        if os.path.islink(source_f):
            self.sources = [get_source_loc(source_f)]

        elif os.path.isdir(source_f):
            self.sources = list(
                map(get_source_loc,
                    sorted(
                        filter(os.path.islink,
                           (os.path.join(source_f, f)
                                for f in os.listdir(source_f))))))

        else:
            self.sources = []

        options_f = os.path.join(destination, self.options_fn)
        if os.path.isfile(options_f):
            self.options = {k: maybe_number(v) for k, v in (x.split(": ") for x in cat_from(options_f).split("\n"))}
        else:
            self.options = {}

        pattern_f = os.path.join(destination, self.pattern_fn)
        if os.path.isfile(pattern_f):
            self.pattern = re.compile(cat_from(pattern_f).rstrip("\n"))
        else:
            self.pattern = self.default_pattern

        exclude_f = os.path.join(destination, self.exclude_fn)
        if os.path.isfile(exclude_f):
            self.exclude = re.compile(cat_from(exclude_f).rstrip("\n"))
        else:
            self.exclude = None

        special_f = os.path.join(destination, self.special_fn)
        if os.path.isfile(special_f):
            self.specials = list(Special.iterparse(cat_from(special_f)))
        else:
            self.specials = []

    def _save(self, filename, content):
        # save data to <destination>/<filename>
        path = os.path.join(self.destination, filename)
        if content is not None:
            with open(path, "w") as f:
                f.write(content)
        elif os.path.exists(path):
            os.unlink(path)

    def save(self):
        # Write settings to disk
        if not os.path.isdir(self.destination):
            os.mkdir(self.destination)

        self._save(self.pattern_fn, self.pattern.pattern if self.pattern is not self.default_pattern else None)
        self._save(self.exclude_fn, self.exclude.pattern if self.exclude is not None else None)
        self._save(self.special_fn, "\n".join(map(Special.source, self.specials)) if self.specials else None)
        self._save(self.options_fn, "\n".join((": ".join((k, opt_value_str(v))) for k, v in self.options.items())) if self.options else None)

        source_f = os.path.join(self.destination, self.source_fn)
        if os.path.islink(source_f):
            oldpath = transport_path(os.readlink(source_f), self.destination, os.curdir)
            if oldpath != self.sources[0].rstrip("/"):
                logger.warn("Updating source link '%s' with '%s'" % (oldpath, self.sources[0]))
            os.unlink(source_f)
        if len(self.sources) > 1 or os.path.isdir(source_f):
            if os.path.isdir(source_f):
                for i, link in enumerate(
                        filter(os.path.islink,
                            sorted((os.path.join(source_f, f) for f in os.listdir(source_f)), key=natural_sort_key))):
                    oldpath = transport_path(os.readlink(link), source_f, os.curdir)
                    if i >= len(self.sources):
                        logger.warn("Removing source link '%s'" % oldpath)
                    elif oldpath != self.sources[i].rstrip("/"):
                        logger.warn("Updating source link '%s' with '%s'" % (oldpath, self.sources[i]))
                    os.unlink(link)
            else:
                os.mkdir(source_f)

            for i, source in enumerate(self.sources):
                make_symlink_in(source, source_f, str(i))

        else:
            make_symlink(self.sources[0], source_f)

        for sp in self.specials:
            if not sp.is_extern:
                continue

            path = os.path.join(self.destination, "..", sp.name)

            if not os.path.isdir(path):
                os.mkdir(path)

            master_f = os.path.join(path, self.master_fn)
            if os.path.islink(master_f):
                oldpath = transport_path(os.readlink(master_f), path, os.curdir)
                if oldpath != self.destination.rstrip("/"):
                    logger.warn("Updating master link '%s' with '%s'" % (oldpath, self.destination))
                os.unlink(master_f)
            make_symlink(self.destination, master_f)

    @property
    def effective_specials(self):
        return itertools.chain(self.specials, self.auto_specials) if self.option("auto_specials") else self.specials

    def option(self, name):
        return self.options[name] if name in self.options else self.default_options.get(name, None)

    def reset(self, *things):
        if "pattern" in things:
            self.pattern = self.default_pattern
        if "exclude" in things:
            self.exclude = None
        if "specials" in things:
            self.specials.clear()
        if "options" in things:
            self.options.clear()

    def print_info(self):
        print("Series Info for %s:" % self.main_name)
        print("-" * (17 + len(self.main_name)))
        print("Sources    |  %s" % ("\n           |  ".join(self.sources)))
        print("Pattern    |  r'%s'%s" % (self.pattern.pattern, " (default)" if self.pattern is self.default_pattern else ""))
        print("Exclude    |  %s" % (("r'%s'" % self.exclude.pattern) if self.exclude else "None"))
        print("Options    |  %s" % self.options)
        print("Specials   |  %s" % ("None"
                                      if not self.specials else
                                      "\n           |  ".join("%-35s :: %s" % ("r'%s'" % special.pattern.pattern, special._properties)
                                                                for special in self.specials)))

    @property
    def flags(self):
        return "".join((f for c, f in [
            (self.pattern is not self.default_pattern, "p"),
            (self.exclude, "e"),
            #(self.option("exclude_parts"), "d"),
            (not self.option("exclude_parts"), "D"),
            (self.option("auto_specials"), "i"),
            (not self.option("auto_specials"), "I"),
            (self.specials, str(len(self.specials))),
        ] if c))

    def process_file(self, filename, subdir=None):
        """
        This is the magic that decides if and where to link to a specific source file.
        """
        # Exclude
        if self.option("exclude_parts") and filename.endswith(".part"):
            return "skip", "partial download"

        elif self.option("exclude_playlists") and (filename[-4:] in (".vml", ".m3u", ".pls")):
            return "skip", "playlist file"

        elif self.exclude and self.exclude.search(filename):
            return "skip", "excluded"

        linkpath = self.destination

        # Specials
        for special in self.effective_specials:
            if bool(subdir) != special.is_subdir or (subdir and subdir != special.subdir):
                continue

            sm = special.match(filename)
            if sm:
                result = special.custom(sm, self)
                if result:
                    return result

                ep = special.get_episode(sm, self.last_special.get(special, 0))
                self.last_special[special] = ep

                if special.is_extern:
                    name = special.name
                    linkpath = os.path.join(self.library_path, name)
                else:
                    name = self.main_name

                linkname = self.link_template.format(series=name, season=special.season, episode=ep)
                break

        else:
            if subdir:
                #logger.warn("Unhandled file in subdir %s: %s" % (subdir, filename))
                return "skip", "in subdirectory"

            # Default values
            data = {
                "series": self.main_name,
                "season": 1,
                "episode": self.last_episode + 1
            }

            # Try to extract info from filename
            m = self.pattern.search(filename)

            if m:
                # Season number (optional)
                if "season" in self.pattern.groupindex and m.group("season"):
                    season = int(m.group("season"))

                # Episode number (mandatory)
                data["episode"] = int(m.group("ep"))

                # Until episode number for files containing multiple episodes (optional)
                if "untilep" in self.pattern.groupindex and m.group("untilep"):
                    data["until_ep"] = int(m.group("untilep"))

            linkname = self.format_linkname(**data)
            self.last_episode = (data["until_ep"] if "until_ep" in data else data["episode"])

        return "link", linkpath, linkname + os.path.splitext(filename)[1]

    def clean_all(self):
        clean_links(self.destination)

        for special in self.specials: # auto_specials doesn't have "extern" specials
            if special.is_extern:
                clean_links(os.path.join(self.destination, "..", special.name))

    def collect(self):
        """
        Collect operations
        """
        self.last_episode = 0 # FIXME: global state is bad
        self.last_special = {}

        for source in self.sources:
            for f in sorted(os.scandir(source), key=natural_name_sort_key):
                if f.is_dir():
                    for ff in sorted(os.scandir(f.path), key=natural_name_sort_key):
                        yield (ff.path, *self.process_file(ff.name, subdir=f.name))
                else:
                    yield (f.path, *self.process_file(f.name))

    def build_vtree(self):
        """
        Build a virtual tree of links
        """
        dirs = collections.defaultdict(dict)

        self.skipped = []

        for src, op, *args in self.collect():
            if op == "skip":
                if self.log_skip:
                    logger.info("Skipped %s (%s)" % (os.path.basename(src), args[0]))
                self.skipped.append(src)
            elif op == "link":
                dirname, linkname = args
                dirs[dirname][linkname] = os.path.relpath(src, dirname)
            else:
                raise ValueError("Collected unknown operation '%s'" % op)

        return dirs

    def build_fstree(self, dirpaths=None):
        """
        Build a tree from existing links
        """
        if dirpaths is None:
            dirpaths = [self.destination] + [os.path.join(self.library_path, special.name)
                                                for special in self.effective_specials
                                                if special.is_extern]
        dirs = {}

        for dirpath in dirpaths:
            dc = dirs[dirpath] = {}
            for f in os.scandir(dirpath):
                if f.name[0] != "." and f.is_symlink():
                    dc[f.name] = os.readlink(f.path)

        return dirs

    DIFF_SAME   = 0
    DIFF_MINUS  = 1
    DIFF_PLUS   = 2

    def diff(self):
        diff = {}

        wtree = self.build_vtree()
        htree = self.build_fstree()

        for dirpath in set(wtree.keys()) | set(htree.keys()):
            wdir = wtree[dirpath] if dirpath in wtree else {}
            hdir = htree[dirpath] if dirpath in htree else {}

            wfiles = set(wdir.keys())
            hfiles = set(hdir.keys())
            bfiles = wfiles & hfiles
            sfiles = {f for f in bfiles if wdir[f] == hdir[f]} # Anchors must be the same in wtree and htree fir relatve paths!!
            cfiles = (bfiles - sfiles)

            ddir = diff[dirpath] = {}
            ddir[self.DIFF_SAME] = {f: wdir[f] for f in sfiles}
            ddir[self.DIFF_MINUS] = {f: hdir[f] for f in (cfiles | (hfiles - wfiles))}
            ddir[self.DIFF_PLUS] = {f: wdir[f] for f in (cfiles | (wfiles - hfiles))}

        return diff

    def run(self, *, dry=False):
        """
        Update this library entry
        """
        for path, diff in self.diff().items():
            for f, target in sorted(diff[self.DIFF_MINUS].items(), key=operator.itemgetter(0)):
                # Check if target still matches?
                logger.info("Remove %s (%s)" % (f, os.path.basename(target)))
                if not dry:
                    os.unlink(os.path.join(path, f))
            for f, target in sorted(diff[self.DIFF_PLUS].items(), key=operator.itemgetter(0)):
                logger.info("Link %s => %s" % (f, os.path.basename(target)))
                lpath = os.path.join(path, f)
                if os.path.exists(lpath):
                    raise FileExistsError("File %s already exists" % f)
                if not dry:
                    os.symlink(target, lpath)
            if not diff[self.DIFF_SAME] and not diff[self.DIFF_PLUS]:
                logger.warn("Library Entry '%s' has no content!" % self.main_name)


###############################################################################
## Argument handling                                                         ##
###############################################################################
class HelpFormatter(argparse.RawTextHelpFormatter):
    def __init__(self, prog):
        super().__init__(prog, max_help_position=16)


def parse_args(argv):
    parser = argparse.ArgumentParser(prog=argv[0], formatter_class=HelpFormatter)

    parser.add_argument("-l", "--library", default=".",
                        help="The library folder to work on [%(default)s]")

    commands = parser.add_subparsers(title="Commands", dest="command")

    # import
    importc = commands.add_parser("import", description="Add a new source location")

    importc.add_argument("source",
                         help="The new source directory")
    importc.add_argument("series",
                         help="The series (directory) name. All non-hidden symlinks inside will be deleted!")

    # unlink
    unlink = commands.add_parser("unlink", description="Remove a source location")

    unlink.add_argument("series",
                        help="The series name")
    unlink.add_argument("source",
                        help="The source directory to remove")

    # config
    config = commands.add_parser("config", description="Modify series configuration")

    config.add_argument("series",
                        help="The series name")

    patterns = config.add_argument_group("Patterns",
            description="Patterns are Python re patterns: https://docs.python.org/3/library/re.html")
    patterns.add_argument("-p", "--pattern", default=None, metavar="PATTERN",
            help="Set the episode pattern. Include a named group <ep>; Optionally <season> and <untilep>")
    patterns.add_argument("-x", "--exclude", default=None, metavar="PATTERN",
            help="Set the exclusion pattern")
    patterns.add_argument("-s", "--special", "--specials", default=[], nargs=2, action="append", metavar=("SPECIAL", "PATTERN"), dest="specials",
            help=("Set the special mapping. This takes 2 arguments and can be specified multiple times.\n"
                  "1st argument: key=value properties separated by '|'.\n"
                  "2nd argument: the matching pattern. It should contain a <ep> group\n"
                  "Valid keys so far are 'type', 'offset', 'name'.\n"
                  "type can be 'special', 'opening', 'ending', 'trailer', 'parody', 'other' and 'extern'.\n"
                  "offset adds a fixed number to all episodes numbers matched by the pattern.\n"
                  "name must only be used with 'extern'. It creates a slave Series to hold the matched episodes in the parent directory.\n"
                  "It's useful for singling out specials that are recorded as independent series in the metadata provider."))
    patterns.add_argument("-a", "--append", action="store_true",
            help="Extend the special mapping instead of replacing it")

    options = config.add_argument_group("Options")
    options.add_argument("-i", "--auto-specials", action="store_true", dest="auto_specials", default=None,
            help="Implicitly add some Specials patterns (default)")
    options.add_argument("-I", "--no-auto-specials", action="store_false", dest="auto_specials", default=None,
            help="Don't add the implicit Specials patterns")

    config.add_argument("--clear", default=[], action="append", choices={"pattern", "exclude", "specials", "options"},
            help="Reset a property to the defaults")

    # Check
    check = commands.add_parser("check", description="Check library and report untracked sources", fromfile_prefix_chars="@")

    check.add_argument("source_roots", nargs="*", metavar="SOURCE_ROOT",
                       help="Directory path containing source directories")

    check.add_argument("-X", "--ignore", action="append", default=[], metavar="DIR",
                       help="Ignore a directory DIR when checking for untracked sources")

    check.add_argument("-I", "--interactive-import", action="store_true",
                       help="Interactively import any untracked sources")

    # Update
    update = commands.add_parser("update", description="Update the symlinks")

    update.add_argument("series", nargs="*", default=[],
                        help="Update only these series (Default: all)")

    # Info
    info = commands.add_parser("info", description="Show information about a series")

    info.add_argument("series", nargs="+",
                      help="Update only these series")

    # Global misc
    parser.add_argument("-U", "--no-update", action="store_true",
                        help="Don't automatically update symlinks. Use '%(prog)s update' later (applicable to import, unlink, config)")
    parser.add_argument("-D", "--dry-run", action="store_true",
            help="Don't save anything to disk Useful combination")
    parser.add_argument("-q", "--quiet", action="store_true")

    return parser.parse_args(argv[1:])


###############################################################################
## Put the pieces together                                                   ##
###############################################################################
# Helpers
def run_update(i, args):
    """ Update the symlinks for a Series Importer """
    try:
        i.run(dry=args.dry_run)
    except:
        logger.exception("Exception running %s" % i)
        return False
    else:
        return True

def get_series_importer(args, series=None):
    if series is None:
        series = args.series

    if series is ".":
        if args.library == "..":
            series = os.path.dirname(os.getcwd())
        else:
            raise ValueError("Using '.' as series is only valid when using '..' for library")

    if args.library != ".":
        return Importer(os.path.join(args.library, series))
    else:
        return Importer(series)

def list_series_paths(library):
    return [de.path
            for de in sorted(os.scandir(library), key=natural_name_sort_key)
            if de.is_dir(follow_symlinks=False)]

def get_series_importers(args, series=None):
    if series:
        return map(functools.partial(get_series_importer, args), series)
    else:
        return map(Importer, list_series_paths(args.library))

def check(i):
    if not i.sources:
        logger.warn("'%s' doesn't have any sources" % i.main_name)
        return False

    have_sources = list(map(os.path.isdir, i.sources))
    if not all(have_sources):
        for source, isdir in zip(i.sources, have_sources):
            if not isdir:
                logger.error("Source link for '%s' doesn't exist: '%s'" % (i.main_name, source))
        return False

    return True

def do_interactive_import(args, sources):
    for source in sources:
        source = os.path.relpath(source, args.library)
        print("Importing from %s:" % source)
        series = input("  Enter Series Name or hit return to skip --> ")

        if not series:
            continue

        i = get_series_importer(args, series)

        if i.sources:
            print("Adding source '%s' to existing '%s'" % (source, series))
        i.sources.append(source)

        if not args.dry_run:
            i.save()

        if not args.no_update:
            run_update(i, args)


# Command Mains
def import_main(args):
    i = get_series_importer(args)

    if args.source not in i.sources:
        if i.sources:
            logger.info("Adding source '%s' to '%s'" % (args.source, args.series))
        i.sources.append(args.source)
    else:
        logger.warn("Source '%s' already linked to '%s'" % (args.source, args.series))

    if not args.dry_run:
        i.save()

    if not args.no_update:
        run_update(i, args)

    return 0

def unlink_main(args):
    i = get_series_importer(args)

    source = transport_path(args.source, os.getcwd(), args.library)
    print (i.sources)

    if source not in i.sources:
        logger.error("Source '%s' not linked to '%s'" % (args.source, args.series))
        return 1
    else:
        i.sources.remove(source)
        logger.warn("Unlinking Source '%s' from '%s'" % (args.source, args.series))

    if not args.dry_run:
        i.save()

    if not args.no_update:
        run_update(i, args)

    return 0

def config_main(args):
    i = get_series_importer(args)

    i.reset(*args.clear)

    if args.pattern:
        i.pattern = re.compile(args.pattern)

    if args.exclude:
        i.exclude = re.compile(args.exclude)

    if args.specials:
        if args.append:
            i.specials.extend(itertools.starmap(Special.parse, args.specials))
        else:
            i.specials = list(itertools.starmap(Special.parse, args.specials))

    for opt in ("auto_specials",):
        if getattr(args, opt) is not None:
            i.options[opt] = getattr(args, opt)

    if not args.dry_run:
        i.save()

    if not args.no_update:
        run_update(i, args)

    return 0

def check_main(args):
    got_dirs = set()

    for i in get_series_importers(args):
        if check(i):
            got_dirs.update(map(os.path.abspath, i.sources))

    if args.source_roots:
        dirs = set(map(os.path.abspath, filter(os.path.isdir, itertools.chain.from_iterable(((os.path.join(f, x) for x in os.listdir(f)) for f in args.source_roots)))))
        ignore = set(map(os.path.abspath, filter(os.path.isdir, (os.path.join(f, x) for x in args.ignore for f in args.source_roots))))
        print(args.ignore, args.source_roots, ignore)
        missing = dirs - got_dirs - ignore
        if missing:
            if args.interactive_import:
                return do_interactive_import(args, missing)
            else:
                print("Found missing directories:\n  %s" % "\n  ".join(os.path.relpath(m) for m in missing))

    return 0

def update_main(args):
    fin_dirs = set()

    for i in get_series_importers(args, args.series):
        if i.destination in fin_dirs:
            logger.debug("Already processed '%s'. Skipping" % i.main_name)
            continue

        logger.info("Processing '%s' (%s)" % (i.main_name, i.flags))

        if not check(i):
            continue

        if run_update(i, args):
            fin_dirs.add(i.destination)

    return 0

def info_main(args):
    logger.setLevel(logging.WARNING)

    for i in get_series_importers(args, args.series):
        i.print_info()
        print()

    return 0


# Program Main
def main(argv):
    logging.basicConfig(level=logging.INFO, format="%(levelname)-5s %(message)s")

    args = parse_args(argv)

    if args.quiet:
        logger.setLevel(logging.WARNING)

    try:
        if args.command == "info":
            return info_main(args)

        if args.command == "import":
            return import_main(args)

        if args.command == "unlink":
            return unlink_main(args)

        if args.command == "config":
            return config_main(args)

        if args.command == "update":
            return update_main(args)

        if args.command == "check":
            return check_main(args)

    except:
        logger.exception("An Exception occured")
        return 255


if __name__ == "__main__":
    sys.exit(main(sys.argv))
