# Homebrew Cask — Open Spark OBS plugin (macOS).
#
# This file is NOT used by CI. To offer `brew install --cask`, create a
# tap repo `github.com/Mundo-Dev0ps/homebrew-tap`, drop this file in its
# `Casks/` dir, and bump `version` + `sha256` on each release:
#
#   shasum -a 256 obs-open-spark-macos.pkg
#
# Users then:
#   brew tap mundo-dev0ps/tap
#   brew install --cask open-spark
#
# (A `flatpak-external-data-checker`-style bump can be automated later.)

cask "open-spark" do
  version "0.1.0"
  sha256 "REPLACE_WITH_PKG_SHA256"

  url "https://github.com/Mundo-Dev0ps/open-spark/releases/download/v#{version}/obs-open-spark-macos.pkg"
  name "Open Spark (OBS plugin)"
  desc "Conversational agent dock for OBS Studio"
  homepage "https://github.com/Mundo-Dev0ps/open-spark"

  depends_on formula: "pipx"

  pkg "obs-open-spark-macos.pkg"

  uninstall pkgutil: "com.obsproject.Studio.Plugin.OpenSpark"

  caveats <<~EOS
    The Open Spark backend is separate:
      pipx install open-spark && open-spark
    Then in OBS: View → Docks → Open Spark.
  EOS
end
