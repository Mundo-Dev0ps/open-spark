# RPM spec for the obs-spark-libre native plugin.
#
# CI uses `fpm` (see .github/workflows/plugin-build.yml) which is
# simpler than maintaining a full spec, but this file is here for
# distro packagers / Fedora COPR who prefer the native rpmbuild path.
#
#   rpmbuild -ba packaging/rpm/obs-spark-libre.spec
#
# Build deps mirror the CI Linux job.

Name:           obs-spark-libre
Version:        0.1.0
Release:        1%{?dist}
Summary:        Spark Libre — native OBS plugin (dock + bridge to LLM backend)

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
Spark Libre exposes a native Qt dock inside OBS Studio that talks to
the external Spark Libre Python backend over loopback HTTP. The dock
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
%{_libdir}/obs-plugins/obs-spark-libre.so
%{_datadir}/obs/obs-plugins/obs-spark-libre/

%changelog
* %(LC_ALL=C date '+%a %b %d %Y') Spark Libre Contributors <noreply@example.com> - 0.1.0-1
- Initial RPM packaging.
