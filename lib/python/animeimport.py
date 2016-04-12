#!/usr/bin/python
# (c) 2015 Taeyeon Mori <orochimarufan.x3@gmail.com>
# Anime Import V2-4

import os
import sys
import re
import itertools
import logging
import argparse


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


def natural_sort_key(s, _nsre=re.compile(r'(\d+)')):
    return [int(text) if text.isdigit() else text.lower() for text in _nsre.split(s)]


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
    default_pattern = re.compile(r"[_ ](E|e|Ep|Episode|ep)?[ _]?(?P<ep>\d+)([Vv]\d+)?[_ ]?[\(\[\.]?")
    default_options = {
        "auto_specials": 1,
        "exclude_parts": 1,
        "exclude_playlists": 1,
    }

    auto_specials = [
        Special.simple("Opening", r"[_ ](NC)?OP[ _]?[^\d]"), # FIXME: HACK
        Special.simple("Opening", r"[_ ]((NC)?OP|Opening)[ _]?(?P<ep>\d+)"),
        Special.simple("Ending", r"[_ ](NC)?ED[ _]?[^\d]"), # FIXME: HACK
        Special.simple("Ending", r"[_ ]((NC)?ED|Ending|Closing)[ _]?(?P<ep>\d+)"),
        Special.simple("Special", r"[_ ](Special|OVA|SP)[ _]?(?P<ep>\d+)?[ _]?"),
        # .nfo files
        Special({"$custom": lambda m, i: ("link", os.path.join(i.destination, i.main_name + ".nfo"))}, re.compile(r".nfo$"))
    ]

    link_template = "{series} S{season:d}E{episode:03d}"

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

        source_f = os.path.join(destination, self.source_fn)
        if os.path.islink(source_f):
            self.source = os.readlink(source_f)
            if not os.path.isabs(self.source):
                self.source = transport_path(self.source, destination, os.curdir)
        else:
            self.source = None

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
            if oldpath != self.source.rstrip("/"):
                logger.warn("Updating source link '%s' with '%s'" % (oldpath, self.source))
            os.unlink(source_f)
        make_symlink(self.source, source_f)

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
    
    def process_file(self, filename, subdir=None):
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
                    linkpath = os.path.join(self.destination, "..", name)
                else:
                    name = self.main_name

                linkname = self.link_template.format(series=name, season=special.season, episode=ep)
                break

        else:
            if subdir:
                #logger.warn("Unhandled file in subdir %s: %s" % (subdir, filename))
                return "skip", "in subdirectory"
            
            m = self.pattern.search(filename)

            if m:
                self.last_episode = int(m.group("ep"))
            else:
                self.last_episode += 1

            linkname = self.link_template.format(series=self.main_name, season=1, episode=self.last_episode) # TODO: allow more seasons?

        return "link", os.path.join(linkpath, linkname + os.path.splitext(filename)[1])

    def clean_all(self):
        clean_links(self.destination)

        for special in self.specials: # auto_specials doesn't have "extern" specials
            if special.is_extern:
                clean_links(os.path.join(self.destination, "..", special.name))

    def run(self, *, dry=False):
        if not dry:
            self.clean_all()

        self.last_episode = 0 # FIXME: global state
        self.last_special = {}

        for f in sorted(os.listdir(self.source), key=natural_sort_key):
            path = os.path.join(self.source, f)
            
            if os.path.isdir(path):
                if self.specials:
                    for ff in sorted(os.listdir(path), key=natural_sort_key):
                        if self.handle_file(os.path.join(f, ff), *self.process_file(ff, subdir=f), dry=dry) != 0:
                            return 1
            else:
                if self.handle_file(f, *self.process_file(f), dry=dry) != 0:
                    return 1
    
    def handle_file(self, f, what, where, *, dry=False):
        if what == "link":
            if os.path.exists(where) and not dry:
                logger.error("LINK %s => %s exists!" % (f, os.path.basename(where)))
                return 1
            else:
                logger.info("LINK %s => %s" % (f, os.path.basename(where)))
            
            if not dry:
                make_symlink(os.path.join(self.source, f), where)

        elif what == "skip":
            logger.info("SKIP %s (%s)" % (f, where))
        
        else:
            assert(False and "Should not be reached")

        return 0

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
        print("Import Info for %s:" % self.main_name)
        print("  Pattern: r'%s'%s" % (self.pattern.pattern, " (default)" if self.pattern is self.default_pattern else ""))
        print("  Exclude: %s" % (("r'%s'" % self.exclude.pattern) if self.exclude else "None"))
        print("  Options: %s" % self.options)
        print("  Specials:%s" % (" (None)" if not self.specials else ""))
        for special in self.specials:
            print("      %-25s :: %s" % ("r'%s'" % special.pattern.pattern, special._properties))

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


###############################################################################
## Argument handling                                                         ##
###############################################################################
class HelpFormatter(argparse.RawTextHelpFormatter):
    def __init__(self, prog):
        super().__init__(prog, max_help_position=16)


def parse_args(argv):
    parser = argparse.ArgumentParser(prog=argv[0], formatter_class=HelpFormatter)

    paths = parser.add_argument_group("Paths")
    paths.add_argument("source",
            help="The source directory")
    paths.add_argument("destination", default=".", nargs="?",
            help="The target directory. Note that all visible symlinks inside will be deleted! (default: working dir)")
    paths.add_argument("-r", "--recurse", action="store_true",
            help="Walk all subdirectories of <destination>")
    paths.add_argument("-S", "--check-unknown", action="append", default=[], metavar="PATH",
            help="Check The source directory for untracked folders. Use with --recurse")
    paths.add_argument("-X", "--check-ignore", action="append", default=[], metavar="FOLDER",
            help="Ignore a folder <FOLDER> when checking for untracked folders")

    patterns = parser.add_argument_group("Patterns",
            description="Patterns are Python re patterns: https://docs.python.org/3/library/re.html")
    patterns.add_argument("-p", "--pattern", default=None, metavar="PATTERN",
            help="Set the episode pattern. Include a named group <ep>")
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

    options = parser.add_argument_group("Options")
    options.add_argument("-i", "--auto-specials", action="store_true", dest="auto_specials", default=None,
            help="Implicitly add some Specials patterns (default)")
    options.add_argument("-I", "--no-auto-specials", action="store_false", dest="auto_specials", default=None,
            help="Don't add the implicit Specials patterns")

    parser.add_argument("--clear", default=[], action="append", choices={"pattern", "exclude", "specials", "options"},
            help="Reset a property to the defaults")
    parser.add_argument("-D", "--dry-run", action="store_true",
            help="Don't save anything to disk Useful combination")
    parser.add_argument("-q", "--quiet", action="store_true")

    return parser.parse_args(argv[1:])


###############################################################################
## Put the pieces together                                                   ##
###############################################################################
def main(argv):
    logging.basicConfig(level=logging.INFO, format="%(levelname)-5s %(message)s")

    args = parse_args(argv)
    
    if args.quiet:
        logger.setLevel(logging.WARNING)
    
    if args.source == "info":
        if args.recurse:
            logger.setLevel(logging.WARNING)
            have_dirs = set()

            for dest in filter(os.path.isdir, (os.path.join(args.destination, x) for x in os.listdir(args.destination))):
                i = Importer(dest)
                if i.destination not in have_dirs:
                    i.print_info()
                    print()
                    have_dirs.add(i.destination)
                # We just ignore dupes from slaves

        else:
            Importer(args.destination).print_info()
            print()
        return 0
    
    if args.recurse:
        if args.pattern or args.exclude or args.specials or args.auto_specials is not None or args.clear:
            logger.error("--recurse can only be combined with --check-unknown")
            return -1

        got_dirs = set()
        OK = 0
        dirs = filter(os.path.isdir, (os.path.join(args.destination, x) for x in os.listdir(args.destination)))

        if args.source == "update":
            fin_dirs = set()

            for dest in dirs:
                i = Importer(dest)
                logger.info("Processing '%s' (%s)" % (dest, i.flags()))
                if not i.source:
                    logger.info("'%s' doesn't seem to be an import. Skipping" % os.path.basename(dest))
                elif i.destination in fin_dirs:
                    logger.info("Already processed '%s'. Skipping" % os.path.basename(dest))
                elif not os.path.exists(i.source):
                    logger.error("Source directory doesn't exist: '%s'" % i.source)
                    OK += 1
                elif not i.run(dry=args.dry_run): # returns 0 (False) on success
                    got_dirs.add(os.path.abspath(i.source))
                    fin_dirs.add(i.destination)
                else:
                    OK += 1

        elif args.source == "check":
            for dest in dirs:
                i = Importer(dest)
                if i.source:
                    got_dirs.add(os.path.abspath(i.source))

        else:
            logger.error("--recurse can only be used with 'update', 'check' and 'info'")
            return -1

        if args.check_unknown:
            dirs = set(map(os.path.abspath, filter(os.path.isdir, itertools.chain.from_iterable(((os.path.join(f, x) for x in os.listdir(f)) for f in args.check_unknown)))))
            ignore = set(map(os.path.abspath, filter(os.path.isdir, itertools.chain.from_iterable(((os.path.join(f, x) for x in args.check_ignore) for f in args.check_unknown)))))
            missing = dirs - got_dirs - ignore
            if missing:
                print("Found missing directories: %s" % "\n                           ".join(missing))

        return OK
    
    elif args.source == "check":
        logger.error("'check' only makes sense in combination with --recurse.")
        return -1

    else:
        if args.check_unknown:
            logger.error("--check-unknown must be used with --recurse")
            return -1

        i = Importer(args.destination)

        if args.source != "update":
            i.source = args.source
        elif not args.source:
            logger.error("'%s' doesn't look like a previously imported directory" % args.destination)
            return -2

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

        return i.run(dry=args.dry_run)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
