"""
Step-by-step guides: installing parts and changing BIOS settings.
Each guide: title, intro, needs (list), steps (list), tips (list), link (optional).
"""

SAFETY = ["Shut down the PC, switch off the power supply at the back, and unplug it.",
          "Touch a bare metal part of the case to discharge static before handling parts."]

GUIDES = {
    "RAM": {
        "title": "Installing memory (RAM)",
        "intro": "About 10 minutes. The hardest part is pushing the sticks in firmly enough.",
        "needs": ["A Phillips screwdriver for the side panel (some cases use thumbscrews)"],
        "steps": SAFETY + [
            "Remove the side panel (usually the left side, looking at the front).",
            "Find the RAM slots next to the processor cooler. If you're replacing sticks, press the "
            "clips at the end of each slot and lift the old sticks out.",
            "With two sticks on a board with four slots, use slots 2 and 4 counting from the "
            "processor (often labeled A2 and B2). Your motherboard manual confirms this.",
            "Line up the notch in the stick with the bump in the slot. It only fits one way.",
            "Press down firmly on both ends until the clips click shut. It takes more force than "
            "you'd expect.",
            "Close the case, plug in, and start the PC. The first start can take a minute or two "
            "while it trains the memory. A black screen during this is normal.",
            "Turn on XMP in the BIOS so the RAM runs at its rated speed (see the XMP guide).",
        ],
        "tips": ["Buy one matched kit rather than mixing with old sticks.",
                 "If the PC won't start, reseat each stick; one not fully clicked in is the usual cause."],
    },
    "Storage": {
        "title": "Installing an NVMe SSD",
        "intro": "About 10 minutes. NVMe drives screw straight onto the motherboard, no cables needed.",
        "needs": ["A small Phillips screwdriver", "Often a tiny M.2 screw (check the motherboard box "
                  "if one isn't already in the slot)"],
        "steps": SAFETY + [
            "Remove the side panel and find an empty M.2 slot, often under a metal heatsink cover "
            "between the processor and graphics card. You may need to remove the graphics card to reach it.",
            "Unscrew the heatsink cover if there is one, and peel the plastic film off its thermal pad.",
            "Slide the SSD into the slot at a slight angle, label facing up, then press it flat and "
            "fasten the small screw (or tool-free clip) at the end.",
            "Put the heatsink back and close the case.",
            "In Windows, right-click Start > Disk Management. It will ask to initialize the new "
            "drive: choose GPT, then right-click the unallocated space > New Simple Volume.",
            "To move Windows onto it, use the drive maker's free cloning tool (Samsung Magician, "
            "Acronis for WD, Crucial's Acronis edition), or install Steam games to it from Steam > "
            "Settings > Storage.",
        ],
        "tips": ["Slots wired to the processor are fastest; the manual shows which ones those are.",
                 "On some boards, using a certain M.2 slot turns off a SATA port. The manual lists these."],
    },
    "GPU": {
        "title": "Installing a graphics card",
        "intro": "About 20 minutes. Check the power supply and case length in My setup first.",
        "needs": ["A Phillips screwdriver", "The new card's power cables from your power supply"],
        "steps": [
            "Download the newest driver for the new card first (NVIDIA App or AMD Software), so it's "
            "ready to install.",
        ] + SAFETY + [
            "Remove the side panel. Unplug the power cables from the old card, remove the screws "
            "holding its bracket to the case, press the release tab on the slot, and lift it out.",
            "Remove any extra slot covers the new card needs if it's thicker than the old one.",
            "Push the new card straight down into the top long slot until the tab clicks, then screw "
            "the bracket to the case.",
            "Connect the power cables. Use separate cables for each connector rather than one "
            "split cable. With a 16-pin connector, push it in until there's no gap at all.",
            "Plug your monitor into the new card (not the motherboard), close the case, and start up.",
            "Install the driver you downloaded.",
        ],
        "tips": ["Heavy cards can sag. Use the support bracket if one came in the box.",
                 "Switching between NVIDIA and AMD? Run Display Driver Uninstaller (DDU) in Safe Mode "
                 "before swapping for the cleanest result."],
    },
    "CPU": {
        "title": "Installing a new processor",
        "intro": "About 45 minutes. Update the BIOS first, while your current processor is still installed.",
        "needs": ["A Phillips screwdriver", "Thermal paste (often pre-applied on new coolers)",
                  "Isopropyl alcohol and a lint-free cloth to clean off old paste"],
        "steps": [
            "Update the BIOS to the newest version for your motherboard, using your current processor. "
            "New processors often won't start on an old BIOS.",
        ] + SAFETY + [
            "Remove the side panel, unplug the cooler's fan cable, and unscrew the cooler. Twist it "
            "gently before lifting so the old paste lets go.",
            "Lift the socket lever, take out the old processor, and drop the new one in, lined up with "
            "the triangle marked on one corner. It should sit flat without pressure.",
            "Lower the lever to lock it (on Intel boards the plastic cover pops off; keep it).",
            "Clean the cooler base, add a pea-sized dot of thermal paste to the processor's center, and "
            "screw the cooler back on evenly, a few turns on each screw at a time.",
            "Reconnect the fan cable to the CPU_FAN header, close up, and start the PC.",
        ],
        "tips": ["Never touch the pins, whether they're on the processor or in the socket.",
                 "High-end chips need a large cooler. A small stock cooler will overheat them."],
    },
    "XMP": {
        "title": "Turning on XMP (full memory speed)",
        "intro": "Two minutes in the BIOS. Memory runs at a slow safe speed until this is on.",
        "needs": [],
        "steps": [],  # filled in per motherboard brand below
        "tips": ["If the PC won't start after this, it resets itself after a few tries. If it doesn't, "
                 "clear the BIOS settings (the manual explains the CMOS clear jumper or button).",
                 "Afterwards, check the Overview: memory should show the new speed.",
                 "Run the benchmark before and after, then compare them on the History page."],
    },
    "REBAR": {
        "title": "Turning on Resizable BAR",
        "intro": "A few minutes in the BIOS. Only do this if Windows was installed in UEFI mode.",
        "needs": [],
        "steps": [
            "First check Windows was installed in UEFI mode: press Win+R, type msinfo32, and look for "
            "BIOS Mode: UEFI. If it says Legacy, stop here; changing this would stop Windows starting.",
            "Restart and press the BIOS key (usually Delete or F2) repeatedly as the PC starts.",
            "Find Above 4G Decoding and set it to Enabled. It's usually under Advanced > PCI "
            "Subsystem Settings or a similar menu.",
            "Set Re-Size BAR Support (sometimes called Smart Access Memory) to Enabled or Auto.",
            "If there's a CSM (Compatibility Support Module) setting, it must be Disabled.",
            "Save and exit (usually F10).",
        ],
        "tips": ["Older cards may need a graphics card firmware update to support it. The card "
                 "maker's website has the tool."],
    },
}

XMP_BY_VENDOR = {
    "msi": ("Delete", ["In the simple EZ Mode screen, click the XMP (or A-XMP) button near the top left "
                       "so it lights up.",
                       "Or press F7 for Advanced Mode, open OC, and set Extreme Memory Profile (X.M.P) "
                       "to Profile 1."]),
    "asus": ("Delete or F2", ["In EZ Mode, find the X.M.P. (or D.O.C.P./EXPO) dropdown and choose "
                              "XMP I or Profile 1.",
                              "Or press F7 for Advanced Mode, open Ai Tweaker, and set Ai Overclock Tuner "
                              "to XMP I."]),
    "gigabyte": ("Delete", ["In Easy Mode, switch on the XMP toggle.",
                            "Or press F2 for Advanced Mode, open Tweaker, and set Extreme Memory Profile "
                            "(X.M.P.) to Profile1."]),
    "asrock": ("F2 or Delete", ["Open OC Tweaker, then DRAM Configuration, and set Load XMP Setting "
                                "to XMP 2.0 Profile 1."]),
    "hp": ("F10", ["Look under Advanced for a memory profile or XMP setting. Many HP desktops don't "
                   "have one; if yours doesn't, the memory speed is fixed and there's nothing to change."]),
    "dell": ("F2", ["Look under Performance (or Overclocking on Alienware) for Memory XMP or a memory "
                    "profile. Many Dell desktops don't have one; if yours doesn't, nothing needs changing."]),
    "lenovo": ("F1 or F2", ["Look under Advanced or Performance for a memory overclocking or XMP option. "
                            "Many Lenovo desktops don't have one; if yours doesn't, nothing needs changing."]),
}


def _vendor(hw):
    b = (hw or {}).get("board") or {}
    text = f"{b.get('board_vendor') or ''} {b.get('system_vendor') or ''}".lower()
    for key, words in (("msi", ("micro-star", "msi")), ("asus", ("asus",)), ("gigabyte", ("gigabyte",)),
                       ("asrock", ("asrock",)), ("hp", ("hp", "hewlett")),
                       ("dell", ("dell", "alienware")), ("lenovo", ("lenovo",))):
        if any(w in text for w in words):
            return key
    return None


def get_guide(key, hw=None):
    """key: RAM, Storage, GPU, CPU, XMP, REBAR. Returns a guide dict with brand-specific steps."""
    g = dict(GUIDES[key])
    g["steps"] = list(g["steps"])
    if key == "XMP":
        vendor = _vendor(hw)
        bios_key, specific = XMP_BY_VENDOR.get(vendor, ("Delete or F2", [
            "Look for a setting named XMP, EXPO, DOCP or Memory Profile, often on the first screen or "
            "in an overclocking (OC / Tweaker) menu, and set it to Profile 1."]))
        name = {"msi": "MSI", "asus": "ASUS", "asrock": "ASRock", "hp": "HP"}.get(vendor, (vendor or "").title())
        g["steps"] = [f"Restart the PC and tap {bios_key} repeatedly as soon as it starts, until the "
                      "BIOS screen appears.", " ".join(specific),
            "Press F10 and confirm to save and restart."]
        if vendor:
            g["intro"] += f" These steps are for {name} motherboards."
    return g
