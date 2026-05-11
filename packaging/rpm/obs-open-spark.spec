# RPM spec for the obs-open-spark native plugin.
#
# CI uses `fpm` (see .github/workflows/plugin-build.yml) which is
# simpler than maintaining a full spec, but this file is here for
# distro packagers / Fedora COPR who prefer the native rpmbuild path.
#
#   rpmbuild -ba packaging/rpm/obs-open-spark.spec
#
# Build deps mirror the CI Linux job.

Name:           obs-open-spark
Version:        0.1.0
Release:        1%{?dist}
Summary:        Open Spark — native OBS plugin (dock + bridge to LLM backend)

License:        MIT
URL:            https://github.com/mundo-devops/open-spark
Source0:        %{name}-%{version}.tar.gz

BuildRequires:  cmake
BuildRequires:  ninja-build
BuildRequires:  gcc-c++
BuildRequires:  qt6-qtbase-devel
BuildRequires:  qt6-qttools-devel
BuildRequires:  obs-studio-devel
BuildRequires:  pkgconfig

Requires:       obs-studio
Requires:       qt6-qtbase
Requires:       qt6-qtbase-gui

%description
Open Spark exposes a native Qt dock inside OBS Studio that talks to
the external Open Spark Python backend over loopback HTTP. The dock
generates OBS overlay HTML, scenes and refinements via an LLM, then
inserts the resulting Browser Sources directly into the running OBS
session.

This plugin is the thin native half of the system; install the
Python backend separately (see project README) or run it as a
container alongside OBS.

%prep
%autosetup

%build
cmake -S plugin -B build -G Ninja \
    -DCMAKE_BUILD_TYPE=RelWithDebInfo \
    -DCMAKE_INSTALL_PREFIX=%{_prefix}
cmake --build build --parallel

%install
DESTDIR=%{buildroot} cmake --install build

%files
%license LICENSE
%doc README.md plugin/README.md
%{_libdir}/obs-plugins/obs-open-spark.so
%{_datadir}/obs/obs-plugins/obs-open-spark/

%changelog
* %(LC_ALL=C date '+%a %b %d %Y') Open Spark Contributors <noreply@example.com> - 0.1.0-1
- Initial RPM packaging.
