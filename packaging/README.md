# Publishing to the AUR

This makes people able to install with `yay -S hypr-settings-git`.

One-time setup:
1. Make an account at https://aur.archlinux.org and add your SSH public key
   (Account → My Account → SSH Public Key).

Publish:
```bash
# clone the (empty) AUR repo
git clone ssh://aur@aur.archlinux.org/hypr-settings-git.git aur-hypr-settings
cd aur-hypr-settings

# copy the PKGBUILD from this folder
cp /path/to/hypr-settings/packaging/PKGBUILD .

# generate metadata, then commit + push
makepkg --printsrcinfo > .SRCINFO
git add PKGBUILD .SRCINFO
git commit -m "Initial release"
git push
```

Test it builds before pushing:
```bash
makepkg -si
```

Updating later: just `git push` new commits to the main repo — the `-git` package
always builds the latest `main`.
