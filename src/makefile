# ===================================================================
# Taeyeon's miscallaneous applications
# (c) 2019 Taeyeon Mori
# ===================================================================
PROGS = keepassxc-print steamns chome overlayns
PROGS_ALL = fakensudo ssh-overlay-kiosk overlayns-static

# Compiler config
CXX = clang++
CXXFLAGS = -std=c++20 -Wall
OPTIMIZE = -O3 -flto
DEBUG = -DDEBUG -g3

# Install config
INSTALL_PATH ?= ~/.local/bin


# -------------------------------------------------------------------
# Common targets
.PHONY: all most install clean
most: $(PROGS)

all: $(PROGS) $(PROGS_ALL)

install: $(PROGS)
	@echo "Installing to INSTALL_PATH = $(INSTALL_PATH)"
	@mkdir -p $(INSTALL_PATH)
	@bash -c 'for prog in $(PROGS); do test -e $$prog && echo "Install $$prog -> $(INSTALL_PATH)" && install -m755 $$prog $(INSTALL_PATH); done'

install-fake-sudo: fakensudo
	install -m755 $< /usr/local/bin/sudo

clean:
	rm $(PROGS) $(PROGS_ALL)


# ------------------------------------------------------------------
# Dependencies
dep_koutil			= koutil.hpp
flg_koutil			=

dep_kofs			= kofs.hpp
flg_kofs			=

dep_koos			= koos.hpp $(dep_kofs)
flg_koos			= $(flg_kofs)

dep_kofd			= kofd.hpp $(dep_kofs)
flg_kofd			= $(flg_kofs)

dep_kofd_pipe		= kofd_pipe.hpp $(dep_kofd)
flg_kofd_pipe		= $(flg_kofd)

dep_koproc			= koproc.hpp $(dep_kofd_pipe)
flg_koproc			= -pthread $(flg_kofd_pipe)

dep_kons			= kons.hpp $(dep_koutil) $(dep_kofd) $(dep_koos)
flg_kons			= $(flg_koutil) $(flg_kofd) $(flg_koos)

dep_kons_clone		= kons_clone.hpp $(dep_kons) $(dep_koproc)
flg_kons_clone		= $(flg_kons) $(flg_koproc)

dep_keepassxc		= keepassxc-browser.hpp $(dep_koproc)
flg_keepassxc		= $(shell pkg-config --cflags --libs libsodium jsoncpp) $(flg_koproc)


# -------------------------------------------------------------------
# Applications
keepassxc-print: keepassxc-print.cpp $(dep_keepassxc)
	$(CXX) $(CXXFLAGS) $(OPTIMIZE) $(flg_keepassxc) -o $@ $<

steamns: steamns.cpp $(dep_kons_clone)
	$(CXX) $(CXXFLAGS) $(OPTIMIZE) $(flg_kons_clone) -o $@ $<

MOverlay2-nsexec: MOverlay2-nsexec.cpp $(dep_kons_clone)
	$(CXX) $(CXXFLAGS) $(OPTIMIZE) $(flg_kons_clone) -o $@ $<

chome: chome.cpp $(dep_koutil) $(dep_kofd) $(dep_koos)
	$(CXX) $(CXXFLAGS) $(OPTIMIZE) $(flg_koutil) $(flg_kofd) $(flg_koos) -o $@ $<

fakensudo: fakensudo.cpp $(dep_kons)
	$(CXX) $(CXXFLAGS) $(OPTIMIZE) $(flg_kons) -o $@ $<

ssh-overlay-kiosk: ssh-overlay-kiosk.cpp $(dep_koutil) $(dep_kofd) $(dep_koos)
	$(CXX) $(CXXFLAGS) $(OPTIMIZE) $(flg_koutil) $(flg_kofd) $(flg_koos) -o $@ $<
	@echo Setting $@ setuid root
	sudo chown root $@
	sudo chmod u+s $@

overlayns: overlayns.cpp $(dep_kons) $(dep_koproc)
	$(CXX) $(CXXFLAGS) $(OPTIMIZE) $(flg_kons) $(flg_koproc) -o $@ $<

overlayns-static: overlayns.cpp $(dep_kons) $(dep_koproc) makefile
	$(CXX) $(CXXFLAGS) $(OPTIMIZE) $(flg_kons) $(flg_koproc) -static -fdata-sections -ffunction-sections -Wl,--gc-sections -o $@ $<

