#!/usr/bin/env python3
"""
Ingest the "Lamb of the Free" ANE/atonement reference (Rillera/Milgrom) into the
ANE-context corpus.

Source: Andrew Remington Rillera, *Lamb of the Free* (Cascade, 2024), building on
Jacob Milgrom's reconstruction of the Levitical cult (with Klawans, Eberhart,
Moffitt, Thiessen, Feder, Wright).

Adds new entries to the existing data/ane_context/*.json dimension files and
augments two existing entries. Idempotent: entries are keyed by id and skipped if
already present; augmentations check for a sentinel before appending. After the
JSON merge it loads the new/changed rows into db/study_bible.db via the existing
parser (INSERT OR REPLACE), so no full rebuild is required.

Routing (per agreed plan):
  - ANE cult data        -> religious_practices (relig_012..021) + augment relig_008
  - covenant blood       -> legal_covenant (legal_009)
  - ransom / death-house -> death_afterlife (death_008)
  - marriage             -> gender_family (gender_008)
  - original sin         -> cosmology_worldview (cosmo_015) + augment cosmo_013 (soul)
  - framing/epistemology -> ane_methodology (method_005..007)
"""

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ANE_DIR = ROOT / "data" / "ane_context"
DB_PATH = ROOT / "db" / "study_bible.db"
sys.path.insert(0, str(ROOT / "src"))


# ---------------------------------------------------------------------------
# New entries, grouped by target dimension file.
# ---------------------------------------------------------------------------

RELIGIOUS_PRACTICES = [
    {
        "id": "relig_012",
        "title": "The Levitical Sacrificial Taxonomy: Five Offerings, Atoning and Non-Atoning",
        "summary": "Leviticus 1-7 presents five distinct offerings with distinct procedures, materials, and stated functions. Only two of them (the purification and reparation offerings) are kipper-effecting; the rest establish presence, homage, and communion. This atoning/non-atoning distinction is load-bearing: which offering a NT text evokes determines what theological work the image can do.",
        "detail": "The cult is differentiated, not monolithic. (1) The 'olah (burnt offering, Lev 1) is wholly consumed and ascends as a 'pleasing aroma' that attracts and entreats the divine presence; kipper language appears (Lev 1:4) but in the gift/entreaty register, not the purgation of specific sin. (2) The minhah (grain offering, Lev 2) is bloodless tribute with no death at all -- its very existence falsifies any definition of sacrifice that requires a victim's death. (3) The shelamim (well-being offering, Lev 3; 7:11-36) culminates in a shared meal (subtypes: todah/thanksgiving, neder/vow, nedabah/freewill); it is explicitly non-atoning and the offerer eats most of the animal. (4) The hatta't (Lev 4:1-5:13) is misnamed 'sin offering': Milgrom showed on grammatical grounds that piel hitte' means 'to decontaminate,' so it is a PURIFICATION offering, required for ritual impurities involving no sin at all -- childbirth (Lev 12), scale disease (Lev 14), genital discharge (Lev 15), corpse contact (Num 19), Nazirite completion (Num 6). A new mother has not sinned; her hatta't purges impurity. A destitute offerer may even bring a bloodless grain hatta't (Lev 5:11-13) and still be forgiven. (5) The 'asham (reparation offering, Lev 5:14-6:7) addresses sacrilege and false oaths through restitution plus a twenty-percent surcharge -- the logic is repayment, not punishment of the animal. Only the hatta't and 'asham are kipper-effecting in the technical purgation sense.",
        "ane_parallels": [
            "Ugaritic ritual texts attest the pair srp (burnt offering, cognate function to 'olah) and slmm (cognate to shelamim) as standard temple/royal liturgy, but lack a developed equivalent of the graded hatta't -- the differentiated purgation system of Leviticus is, in its developed form, distinctive",
            "Mesopotamian and Egyptian daily cult is fundamentally provisioning (the god's meals); Israel keeps the institutional form but not a victim's-death definition of sacrifice (the bloodless minhah and flour hatta't)",
            "The graded blood manipulations of the hatta't, indexed to how far impurity has penetrated the sanctuary, have no close ANE analogue at that level of development"
        ],
        "interpretive_significance": "Reading any NT 'sacrifice' language requires first asking WHICH offering is in view, because the classes do different work. Passover and covenant blood (the most frequent NT images) belong to non-atoning, liberation-and-meal institutions; the Yom Kippur / hatta't image (Hebrews, Rom 3:25) is purgative; the 'olah/gift register fits Eph 5:2 and Rom 12:1. Collapsing all five into one undifferentiated 'sacrifice = a death that pays for sin' is exactly the move the text does not license.\n\nConfidence: the five-fold taxonomy and the atoning/non-atoning distinction are demonstrable from Lev 1-7 and are the mainstream account. The internal 'plumbing' is contested only at the edges (Roy Gane argues the ordinary hatta't carries the offerer's evil into the sanctuary rather than purging it out -- a reversed direction of flow, but still non-penal). See relig_013 (kipper as purgation) and method_007 (atonement test case).",
        "period": "exodus_conquest",
        "books": [
            {"book": "Lev", "chapter_start": 1, "chapter_end": 7},
            {"book": "Heb", "chapter_start": 9, "chapter_end": 10}
        ],
        "key_references": ["Lev 1:1-9", "Lev 2:1-3", "Lev 3:1-5", "Lev 4:1-12", "Lev 5:11-13", "Lev 5:14-16", "Lev 7:11-21", "Heb 10:1-14"],
        "scholarly_sources": ["Milgrom, Leviticus 1-16 (Anchor Bible)", "Rillera, Lamb of the Free (Cascade, 2024)", "Eberhart, The Sacrifice of Jesus", "Klawans, Purity, Sacrifice, and the Temple"]
    },
    {
        "id": "relig_013",
        "title": "Kipper as Purgation: Blood on the Sancta and the Akkadian kuppuru Cognate",
        "summary": "In cultic contexts kipper means 'purge, wipe off' (cognate to Akkadian kuppuru), and its blood is applied to the sancta -- altar horns, veil, kapporet -- never to the person whose impurity occasioned the offering. The Babylonian Akitu rite of wiping the Ezida shrine with a ram's carcass is the clearest ANE comparandum: the object purified is the building, not a person.",
        "detail": "Akkadian kuppuru, 'to wipe, rub off, purify,' is a standard term in Mesopotamian ritual texts. In the Akitu (New Year) festival, on 5 Nisan the Ezida shrine of Nabu in Esagila was purged (kuppuru) by wiping the sanctuary with the carcass of a decapitated ram; the ram's body and the slaughterer were then expelled from the city, and the exorcist and slaughterer stayed outside because they had absorbed impurity -- both features running parallel to Leviticus 16, where the sanctuary is purged and the handlers of the goat and burned hatta't carcasses must wash before re-entering the camp (Lev 16:26-28). Within the Hebrew Bible the direct objects of cultic kipper are sancta: the altar (Lev 8:15; 16:18-19; Ezek 43:20, 26), the sanctuary (Lev 16:16-20), the house (Lev 14:53). When a person benefits, the idiom is kipper 'al, 'effect purgation on behalf of,' never kipper with the person as direct object. Milgrom's formula: the hatta't blood is a 'ritual detergent.' The two apparent exceptions confirm the rule -- priestly ordination blood on ear/thumb/toe (Exod 29:20-21; Lev 8:23-24) consecrates the priests as quasi-sancta, and the healed metsora' rite (Lev 14:14) re-aggregates a restored person -- in neither case does blood carry sin or absorb punishment. The non-cultic sense of kpr as 'ransom' (kofer, Exod 21:30; Num 35:31-32) is real but a distinct register that the priestly texts do not conflate with cultic purgation.",
        "ane_parallels": [
            "Babylonian Akitu festival: the Ezida shrine purged (kuppuru) by wiping it with a decapitated ram's carcass, after which carcass, slaughterer, and exorcist are expelled as impurity-bearers -- structurally parallel to Lev 16:16-28",
            "Hittite zurki (blood) rites (Feder): blood applied to purify and consecrate cult objects, buildings, and divine images -- the closest known functional analogue to the hatta't, running in the purgation direction",
            "Akkadian kuppuru as a standard wiping/cleansing verb in Mesopotamian ritual texts, sharing the semantic field of Hebrew cultic kipper"
        ],
        "interpretive_significance": "Romans 3:25's hilasterion is the LXX term for the kapporet (Exod 25:17-22 LXX; cf. Heb 9:5), the place of purgation -- so its demonstrable register is the Yom Kippur purgation site, with God as the SUBJECT who provides it, not an object placated by it. Hebrews maps blood to the purification of defiled things and consciences (Heb 9:13-14, 22-23), not to punishment. Atonement in this corpus is therefore a function (purgation that preserves divine residence and restores access), not a mechanism of appeasement or penalty-transfer.\n\nConfidence: the kuppuru cognate, the Akitu parallel, blood-on-sancta, and hilasterion=kapporet are demonstrable. Contested edge: Gane reverses Milgrom's direction of flow (evil carried in, not purged out); both agree the system is non-penal. See relig_012, relig_014, relig_021.",
        "period": "exodus_conquest",
        "books": [
            {"book": "Lev", "chapter_start": 4, "chapter_end": 4},
            {"book": "Lev", "chapter_start": 16, "chapter_end": 16},
            {"book": "Lev", "chapter_start": 8, "chapter_end": 8},
            {"book": "Ezk", "chapter_start": 43, "chapter_end": 45},
            {"book": "Rom", "chapter_start": 3, "chapter_end": 3}
        ],
        "key_references": ["Lev 4:6-7", "Lev 4:25", "Lev 16:14-19", "Lev 8:15", "Ezek 43:20", "Exod 25:17-22", "Rom 3:25", "Heb 9:11-14"],
        "scholarly_sources": ["Milgrom, Leviticus 1-16 (Anchor Bible)", "Feder, Blood Expiation in Hittite and Biblical Ritual (SBL)", "Wright, The Disposal of Impurity", "Moffitt, Rethinking the Atonement"]
    },
    {
        "id": "relig_014",
        "title": "Lifeblood, Not Death: Blood as Life Applied Against Death",
        "summary": "Leviticus 17:11 grounds the rite in life (nefesh), not death: 'it is the blood that effects purgation by means of the life.' Impurity's common denominator is death; the blood-gesture vocabulary (natan, hizzah, yatsaq, hyssop) daubs life-substance over the breach-points where death has registered. Slaughter is preparatory, never the freighted moment.",
        "detail": "The stated mechanism is life, not death, with three demonstrable corollaries: (1) lay slaughter -- the offerer, a layperson, kills the animal (Lev 1:5; 3:2; 4:24), while the priestly acts are blood manipulation and altar service; if death were the freighted moment it would not be delegated to laity; (2) the slaughter verb shahat is butchery, not execution vocabulary, and no text describes the animal as punished, condemned, or suffering; (3) a destitute offerer may bring a bloodless flour hatta't (Lev 5:11-13) and be forgiven -- kipper without death, fatal to any 'death-as-penalty' reading of the system's logic. Milgrom's aerial view: every major ritual impurity is death or its simulacrum -- the corpse is the paradigm (Num 19), tsara'at renders one 'like the dead' (Num 12:12, Miriam 'as one dead'), genital discharge is the loss of life-fluids (Lev 15). The one purgative is blood because 'the life is in the blood,' and the metsora' rite makes the polarity explicit: living water (mayim hayyim), blood, and red materials (cedar, scarlet, the red cow of Num 19) array life-substances against death. The gesture vocabulary is application vocabulary -- natan ('put' on the horns), hizzah ('sprinkle' before the veil), yatsaq ('pour out' at the base), and kipper itself ('wipe'); hyssop is the recurring brush (Exod 12:22; Lev 14:4-7; Num 19:18; Ps 51:7). Blood is life painted over the wound death has made.",
        "ane_parallels": [
            "The red-cow rite (Num 19): ashes of a red cow in living water against corpse-impurity -- red life-substances marshalled against the strongest contaminant, death",
            "Hyssop as a ritual applicator (a brush by function) across apotropaic and purificatory rites, from the Passover doorposts to the metsora' rite to corpse-impurity water",
            "The metsora' rite (Lev 14): blood and oil on ear, thumb, and toe re-aggregating a person returning from the realm of the dead, mirroring the priestly consecration gesture (Lev 8:23-24)"
        ],
        "interpretive_significance": "The NT keeps the application grammar intact rather than swapping it for a penal vocabulary the cult never used: 'the blood of sprinkling' (Heb 12:24; 1 Pet 1:2), 'hearts sprinkled clean' (Heb 10:22). The rites repeat because mortal life can only cover the wound and must be reapplied (Heb 10:1-4); the 'indestructible life' (Heb 7:16) closes it -- same grammar, not a switch to punishment. 'The life is in the blood,' never 'the death.'\n\nConfidence: Lev 17:11's life-mechanism, lay slaughter, the bloodless flour hatta't, and the application-gesture vocabulary are demonstrable. That impurity's unifying denominator is death is Milgrom's strong inference -- widely but not universally followed. See relig_013, relig_018.",
        "period": "exodus_conquest",
        "books": [
            {"book": "Lev", "chapter_start": 17, "chapter_end": 17},
            {"book": "Lev", "chapter_start": 14, "chapter_end": 15},
            {"book": "Num", "chapter_start": 19, "chapter_end": 19},
            {"book": "Heb", "chapter_start": 9, "chapter_end": 10}
        ],
        "key_references": ["Lev 17:11", "Lev 5:11-13", "Num 19:11-19", "Num 12:12", "Lev 14:4-7", "Exod 12:22", "Ps 51:7", "Heb 9:22", "Heb 10:1-4"],
        "scholarly_sources": ["Milgrom, Leviticus 1-16 (Anchor Bible)", "Feder, Blood Expiation in Hittite and Biblical Ritual", "Moffitt, Atonement and the Logic of Resurrection (Brill)", "Rillera, Lamb of the Free (Cascade, 2024)"]
    },
    {
        "id": "relig_015",
        "title": "Hand-Leaning (samakh): Ownership and Identification, Not Sin-Transfer",
        "summary": "The one-handed samakh gesture (Lev 1:4; 3:2; 4:4) designates the animal as the offerer's own and the offering as on his behalf. It cannot be sin-transfer, because a sin-laden animal would be impure, and impurity is categorically barred from the altar. The single transfer rite in the Torah -- the two-handed scapegoat with confession -- is deliberately withheld from sacrificial status.",
        "detail": "Samakh marks identification and ownership: this animal is mine, offered for me. Sin-transfer is systemically impossible at the altar for a demonstrable reason -- an animal loaded with sin would be impure, and impure things are barred (Lev 22:17-25); in fact the hatta't is 'most holy' and whatever touches its flesh becomes holy, not defiled (Lev 6:25-29). The one unambiguous transfer rite proves the point by contrast: the scapegoat of Leviticus 16:21-22 receives TWO hands plus verbal confession explicitly transferring 'all the iniquities of the Israelites' -- and exactly there the system withholds sacrifice: the goat for Azazel is not slaughtered, its blood is not manipulated, it is not offered on the altar; it is driven out. Sin-transfer and sacrifice are mutually exclusive operations in Leviticus 16, performed on two different goats. The conclusion is precise: the one clear case of sin-transfer in the Torah is non-sacrificial, and the rites that are sacrificial involve no transfer.",
        "ane_parallels": [
            "ANE elimination/disposal rites (Hittite and Syrian) form a recognized ritual genre, transfer-and-banishment, distinct from altar sacrifice -- the genre the scapegoat belongs to (see relig_008)",
            "Mesopotamian substitution rituals (substitute king, namburbi figurine-transfer) likewise transfer fate/penalty onto a carrier that is destroyed or expelled, never offered on an altar (see relig_016)",
            "The two-handed, confession-accompanied gesture of Lev 16:21 is formally distinct from the one-handed samakh of the altar offerings -- the texts mark the difference deliberately"
        ],
        "interpretive_significance": "The laying-on of hands at the altar cannot be read as the offerer's sin passing into the victim to be punished in his place; it is identification, not penal imputation. The NT's one possible scapegoat allusion is at most faint (perhaps Matt 27:15-26; Barnabas 7 makes it explicit only later), and it belongs to the elimination register (removal of sin), not the altar register (purgation by blood). Demonstrable. See relig_008 (Azazel) and relig_016 (ANE substitution was non-sacrificial).",
        "period": "exodus_conquest",
        "books": [
            {"book": "Lev", "chapter_start": 1, "chapter_end": 4},
            {"book": "Lev", "chapter_start": 16, "chapter_end": 16}
        ],
        "key_references": ["Lev 1:4", "Lev 3:2", "Lev 4:4", "Lev 16:21-22", "Lev 6:25-29", "Lev 22:17-25"],
        "scholarly_sources": ["Milgrom, Leviticus 1-16 (Anchor Bible)", "Wright, The Disposal of Impurity", "Rillera, Lamb of the Free (Cascade, 2024)"]
    },
    {
        "id": "relig_016",
        "title": "ANE Substitution Existed but Was Not Sacrifice: the Substitute King, Namburbi, and zurki Blood Rites",
        "summary": "Mesopotamia possessed genuine penalty- and fate-transfer rituals -- the substitute king (sar puhi) and namburbi figurine-transfer -- with clear vocabulary and procedure. The Levitical altar cult conspicuously contains none of this machinery. Where Israel keeps transfer-and-disposal it is the non-sacrificial scapegoat, and the nearest blood-rite analogue (Hittite zurki) runs in the purgation, not the penal, direction.",
        "detail": "This is the decisive contrastive datum. The sar puhi (substitute king) ritual, attested from the Old Babylonian period through the Neo-Assyrian archives, enthroned a surrogate when omens portended the king's death; the substitute absorbed the fate, was put to death, and the true king resumed the throne. Namburbi rituals routinely transferred portended evil onto figurines, animals, or objects that were then destroyed or sent down the river. These are real penalty-transfer and fate-transfer mechanisms, named and practiced in the very environment Israel inhabited. The altar cult of Leviticus contains exactly none of it. The nearest blood-rite parallel runs the other way: Feder's study of the Hittite zurki rites shows second-millennium Anatolian and north-Syrian rituals applying blood to purify and consecrate cult objects, buildings, and images -- the closest functional analogue to the hatta't, operating in the purgation register. The Hittite Instructions for Temple Officials supply a further parallel: offenses against the god's household are answered by the deity's own direct judgment on the offender and his line -- Milgrom's comparandum for kareth as divine (not court-administered) extirpation.",
        "ane_parallels": [
            "Sar puhi (substitute king): a surrogate enthroned, made to absorb the king's portended death, then killed so the true king survives -- attested from Old Babylonian through Neo-Assyrian times (ANET; SAA X correspondence)",
            "Namburbi rituals: portended evil transferred onto figurines, animals, or objects, then destroyed or floated downriver -- genuine fate-transfer machinery distinct from altar offerings",
            "Hittite zurki blood rites (Feder): blood applied to purify and consecrate objects, buildings, and divine images -- the nearest analogue to the hatta't, in the purgation direction"
        ],
        "interpretive_significance": "The Levitical system stands in an environment where substitutionary ritual was available, named, and practiced -- and conspicuously declines to build its sacrifices on it. Reading Levitical sacrifice as penal substitution therefore imports the one mechanism the cult pointedly excludes, while the genuine ANE substitution rites are precisely the non-sacrificial ones. This is the historical pivot of the whole non-penal case. Demonstrable. See relig_015, relig_019, and method_007.",
        "period": "exodus_conquest",
        "books": [
            {"book": "Lev", "chapter_start": 1, "chapter_end": 17},
            {"book": "Num", "chapter_start": 15, "chapter_end": 15}
        ],
        "key_references": ["Lev 16:8-10", "Lev 16:20-22", "Lev 4:1-12", "Num 15:30-31"],
        "scholarly_sources": ["ANET (Pritchard, 3rd ed.): substitute-king and namburbi materials", "State Archives of Assyria X (Neo-Assyrian correspondence on sar puhi)", "Feder, Blood Expiation in Hittite and Biblical Ritual", "Wright, The Disposal of Impurity"]
    },
    {
        "id": "relig_017",
        "title": "Child Sacrifice (molk): the Boundary Israel's Cult Polices",
        "summary": "The molk environment -- Punic and Phoenician child offerings, and Mesha's sacrifice of his firstborn on the wall (2 Kgs 3:27) -- shows that escalating sacrifice to the offerer's own child was live practice in Israel's world. The Torah prohibits it absolutely, requires the firstborn to be redeemed rather than offered, and the prophets call the very idea unthinkable.",
        "detail": "Punic and Phoenician molk offerings and the Moabite evidence (Mesha, 2 Kgs 3:27) attest a cultic environment in which the surrender of one's own child could be offered to purchase divine favor or deliverance. Against this the Torah legislates: child sacrifice is prohibited absolutely (Lev 18:21; 20:2-5; Deut 12:31); the firstborn, who belongs to YHWH, is REDEEMED, not offered (Exod 13:13-15; 34:20); and the prophets treat the practice as something that never even entered YHWH's mind (Jer 7:31; 19:5). Micah's rejected escalation runs the logic to its end and refuses it: 'Shall I give my firstborn for my transgression...? He has shown you, O mortal, what is good' (Mic 6:6-8). The contrast is load-bearing: the logic that the deity's favor is purchased by the surrender of a life -- the nearest ANE analogue to a penal-satisfaction economy -- is exactly the logic Israel's cult is written against.",
        "ane_parallels": [
            "Punic tophet evidence (Carthage and the western Phoenician colonies): urns of cremated infants associated with molk dedications (the scale and interpretation are debated, but the practice is attested)",
            "Phoenician/Canaanite molk offerings of children to a deity for deliverance or favor",
            "The Moabite king Mesha sacrificing his firstborn son on the wall during a siege (2 Kgs 3:27), with the besieging Israelite coalition withdrawing"
        ],
        "interpretive_significance": "When penal-substitution language frames the Father as purchasing favor or satisfying wrath through the death of his Son-as-victim, it reproduces precisely the molk logic the Torah outlaws and the prophets call unthinkable -- the surrender of a child's life to buy divine favor. The biblical cult is built in the opposite direction: firstborns are redeemed, not offered. Confidence: the biblical prohibition and the firstborn-redemption datum are demonstrable; the scale and exact ritual mechanics of the Punic tophet remain debated. See relig_016 and method_007.",
        "period": "divided_monarchy",
        "books": [
            {"book": "Lev", "chapter_start": 18, "chapter_end": 20},
            {"book": "Deu", "chapter_start": 12, "chapter_end": 12},
            {"book": "2Ki", "chapter_start": 3, "chapter_end": 3},
            {"book": "Jer", "chapter_start": 7, "chapter_end": 7},
            {"book": "Mic", "chapter_start": 6, "chapter_end": 6}
        ],
        "key_references": ["Lev 18:21", "Lev 20:2-5", "Deut 12:31", "Exod 13:13-15", "Exod 34:20", "2 Kgs 3:27", "Jer 7:31", "Mic 6:6-8"],
        "scholarly_sources": ["Levenson, The Death and Resurrection of the Beloved Son (Yale)", "Day, Molech: A God of Human Sacrifice in the Old Testament", "Milgrom, Leviticus (Anchor Bible)", "Rillera, Lamb of the Free (Cascade, 2024)"]
    },
    {
        "id": "relig_018",
        "title": "Ritual Impurity and Moral Impurity Are Distinct Systems",
        "summary": "Klawans, building on Milgrom, distinguishes two impurity systems in the priestly and holiness texts. Ritual impurity (corpse, childbirth, discharge, scale disease) is contagious, temporary, non-sinful, and remedied by washing, time, and the purification offering. Moral impurity (idolatry, sexual sin, bloodshed) is not contact-contagious; it pollutes sinner, land, and sanctuary from afar and is addressed by punishment, justice, exile, and the annual purgation.",
        "detail": "Ritual impurity arises from corpses, childbirth, genital discharges, and scale disease; its sources are largely unavoidable and sometimes obligatory (burying the dead, procreation); it is contagious by contact, temporary, NOT sinful, and remedied by washing, the passage of time, and the hatta't. Moral impurity arises from idolatry, sexual immorality, and bloodshed (Lev 18:24-30; 19:31; 20:1-3; Num 35:33-34); it is not contact-contagious, but it pollutes the sinner, the land, and the sanctuary from a distance; it is not remedied by the ordinary hatta't but by punishment, atonement of the land through justice (Num 35:33), exile (Lev 18:28), and at the systemic level by the annual Yom Kippur purgation of the sanctuary's accumulated defilement (Lev 16:16). The grids must not be merged: a corpse-contaminated Israelite has not sinned, and an idolater is not merely 'ritually unclean.'",
        "ane_parallels": [
            "ANE purity codes (Mesopotamian, Hittite, Egyptian) likewise govern access to sacred space and distinguish contagious ritual states from offenses against the deity (see relig_004 for the shared boundary-maintenance logic)",
            "Mesopotamian namburbu purification ceremonies address ritual contamination, while offenses against the god's household are answered by the deity directly (Hittite Instructions for Temple Officials) -- the two-track structure parallels Israel's ritual/moral split",
            "The cross-culturally attested association of corpse, disease, and discharge with impurity, treated by washing and time"
        ],
        "interpretive_significance": "The NT's purity language about Jesus's work spans both registers: cleansing of conscience (Heb 9:14), purification of a people (Titus 2:14), and -- on the ritual side -- Thiessen's demonstration that the Gospels portray Jesus as a contagious source of HOLINESS who reverses ritual impurity at its sources (corpse, discharge, lepra) without himself sinning or being defiled. Keeping the two systems distinct prevents misreading either Levitical law or the Gospel healings. Demonstrable. Extends relig_004; see relig_019 for the moral-impurity tier the cult cannot reach by ordinary offering.",
        "period": "exodus_conquest",
        "books": [
            {"book": "Lev", "chapter_start": 11, "chapter_end": 20},
            {"book": "Num", "chapter_start": 35, "chapter_end": 35},
            {"book": "Mrk", "chapter_start": 5, "chapter_end": 5}
        ],
        "key_references": ["Lev 11:1-47", "Lev 15:1-33", "Lev 18:24-30", "Num 35:33-34", "Lev 16:16", "Heb 9:14", "Titus 2:14", "Mark 5:25-34"],
        "scholarly_sources": ["Klawans, Impurity and Sin in Ancient Judaism (Oxford)", "Milgrom, Leviticus 1-16 (Anchor Bible)", "Thiessen, Jesus and the Forces of Death (Baker Academic)"]
    },
    {
        "id": "relig_019",
        "title": "The Cult's Ceiling: Intentional Sin Lies Wholly Beyond Sacrificial Remedy",
        "summary": "The system states its own limit. No Levitical offering addresses intentional, defiant sin (Num 15:27-31): the defiant sinner (beyad ramah, 'with a high hand') is cut off (kareth), his iniquity upon him. Deliberate wrongs reach the altar only after confession and restitution, so it is the repentance, not the offering, that converts them. Forgiveness of defiance is the divine householder's prerogative, never a cultic product.",
        "detail": "Numbers 15:27-31 covers the inadvertent sinner (bishgagah) and then states the limit: the one who acts defiantly 'blasphemes the LORD... shall be cut off... his iniquity is upon him.' Its outcome is kareth -- the divine householder's own severance, distinguished from court-administered penalties because the offense lies in YHWH's direct jurisdiction. The one place deliberate wrongs reach the altar confirms the rule: the 'asham cases of knowing fraud and false oath (Lev 6:1-7; Num 5:6-8) become expiable only after voluntary confession and restitution plus the surcharge -- the repentance converts the offense to expiable status, and the offering ratifies a restoration already begun. Yom Kippur does not breach this ceiling; it legislates it: the day's benefit is conditioned on self-affliction, and 'whoever does not afflict himself... shall be cut off' (Lev 16:29-31; 23:29-30). The purge maintains the house; it does not restore the defector. At the systemic level the prophets locate the remedy for covenant treachery beyond the cult: a new covenant in which 'I will forgive their iniquity and remember their sin no more' (Jer 31:31-34), a new heart God himself gives (Ezek 36:25-27), the broken spirit no offering covers (Ps 51:16-17). Two data confirm that forgiveness is the householder's to grant: forgiveness by fiat with no sacrifice named (2 Sam 12:13; Ps 32:1-5) and Jesus forgiving on his own authority before any cross-event (Mark 2:5-10; Luke 7:47-48).",
        "ane_parallels": [
            "Hittite Instructions for Temple Officials (ANET 207-210): offenses against the god's household provoke the deity's own judgment on the offender and his entire line -- Milgrom's comparandum for kareth as divine, not court-administered, extirpation reaching the offender's lineage",
            "ANE temple law generally distinguishes ritual maintenance of the deity's house from the householder's direct prerogative over defiance within his jurisdiction",
            "The widely attested ANE principle that grave offense against a divine patron is answered by the patron himself rather than processed through routine cult"
        ],
        "interpretive_significance": "That the cult never operated at the tier of defiant sin is common ground across Milgrom, Rillera, and their credible critics -- it is one of the most secure points in the whole field. The cult does not fail here; it was never designed to operate here, and it points past itself to a forgiveness only the householder grants. This is precisely the gap the NT's 'forgiveness of sins' language fills (Jer 31:34 cited in Heb 8:12; 10:16-18; Acts 26:18), which is covenant-renewal language, not a sacrificial mechanism. Demonstrable. See relig_012 and method_007.",
        "period": "exodus_conquest",
        "books": [
            {"book": "Num", "chapter_start": 15, "chapter_end": 15},
            {"book": "Lev", "chapter_start": 16, "chapter_end": 16},
            {"book": "Lev", "chapter_start": 23, "chapter_end": 23},
            {"book": "Jer", "chapter_start": 31, "chapter_end": 31},
            {"book": "Ezk", "chapter_start": 36, "chapter_end": 36}
        ],
        "key_references": ["Num 15:27-31", "Lev 6:1-7", "Num 5:6-8", "Lev 16:29-31", "Lev 23:29-30", "Jer 31:31-34", "Ezek 36:25-27", "2 Sam 12:13", "Mark 2:5-10"],
        "scholarly_sources": ["Milgrom, Leviticus 1-16 (Anchor Bible)", "Rillera, Lamb of the Free (Cascade, 2024)", "Klawans, Purity, Sacrifice, and the Temple (Oxford)"]
    },
    {
        "id": "relig_020",
        "title": "Passover Is Apotropaic and Communal, Not Atoning",
        "summary": "The original Passover (Exodus 12) has no altar, no priest, no sanctuary blood rite, and no kipper vocabulary. The doorpost blood wards off the Destroyer and the lamb is eaten in a household meal -- an apotropaic and liberation rite, classed in later practice with the well-being (shelamim) family, never applied to persons for forgiveness.",
        "detail": "Demonstrable from Exodus 12: the blood on the doorposts wards off the Destroyer (Exod 12:13, 23); the verb pasah means God protectively passes over or stands guard; the lamb is then eaten in a household meal. Form-critically the pesah aligns with apotropaic blood rites known across the ANE (threshold and doorway blood applications against destructive agents), not with purgation offerings -- it has no altar, no priest, no sanctuary, and no kipper language. In the later cult the pesah is classified in practice with the shelamim family: slaughtered by laity or Levites, eaten by the offerers, never applied to persons for forgiveness.",
        "ane_parallels": [
            "Mesopotamian Namburbi-type apotropaic rites and Arslan Tash-type protective texts: blood and incantations applied at thresholds and doorways to bar destructive agents from a house",
            "The household-meal form of the pesah aligns with domestic ritual rather than temple purgation (Bokser, The Origins of the Seder)",
            "ANE threshold/doorway protective applications generally, a genre distinct from sanctuary blood manipulation"
        ],
        "interpretive_significance": "The NT's Passover images therefore evoke liberation, protection, and a covenant-constituting meal, not penal exchange. '​Christ our Passover has been sacrificed' (1 Cor 5:7) grounds an exhortation to communal purity ('cleanse out the old leaven') -- the Passover logic of a household made ready; 'the Lamb of God who takes away (airon) the sin of the world' (John 1:29) is removal/liberation language; Revelation's slain-yet-standing Lamb evokes liberation and enthronement. Tellingly, all four gospels time the crucifixion to Passover (the liberation festival), and no NT text associates the death with Yom Kippur's calendar -- if the native register were penal purgation, the Day of Purgations is the date the typology would demand. Demonstrable. See relig_021 (the atoning image, in Hebrews) and legal_009 (covenant blood).",
        "period": "exodus_conquest",
        "books": [
            {"book": "Exo", "chapter_start": 12, "chapter_end": 12},
            {"book": "1Co", "chapter_start": 5, "chapter_end": 5},
            {"book": "Jhn", "chapter_start": 1, "chapter_end": 1},
            {"book": "Jhn", "chapter_start": 19, "chapter_end": 19},
            {"book": "Rev", "chapter_start": 5, "chapter_end": 5}
        ],
        "key_references": ["Exod 12:1-13", "Exod 12:21-27", "1 Cor 5:7", "John 1:29", "John 19:36", "Rev 5:6-10"],
        "scholarly_sources": ["Bokser, The Origins of the Seder (UC Press)", "Rillera, Lamb of the Free (Cascade, 2024)", "Milgrom, Leviticus (Anchor Bible)"]
    },
    {
        "id": "relig_021",
        "title": "Yom Kippur in Hebrews: Purgation and Entrance, Not Penalty",
        "summary": "Hebrews is the New Testament's one sustained Yom Kippur / purification-offering argument, and it follows the Levitical grammar exactly: what matters is the presentation of blood in the sanctuary, the purification of defiled things and consciences, and the priest's entrance into God's presence -- mapped onto resurrection and ascension, not onto the moment of death.",
        "detail": "Hebrews' mechanics are purgation and entrance: blood presentation in the sanctuary (Heb 9:7, 11-12, 23-26), the purification of defiled things and consciences (9:13-14, 22-23), and the high priest's entrance into God's presence. Moffitt's point, which Rillera adopts: in the Levitical sequence the slaughter is preliminary; the atoning moment is the presentation of LIFE before God -- which Hebrews maps onto resurrection and ascension ('he entered once for all by his own blood,' 9:12; 'now to appear in the presence of God for us,' 9:24). Hebrews 9:22's 'almost everything is purified with blood' carefully preserves the bloodless exceptions (Lev 5:11-13; Num 31:22-24) and names purification, not punishment, as blood's function. Romans 3:25's hilasterion is the LXX term for the kapporet -- the purgation site -- with God as the one who provides it. The 'once for all' is the indestructible life (Heb 7:16) closing the wound that mortal life could only cover and reapply (Heb 10:1-4): the same application grammar, not a switch to penal exchange.",
        "ane_parallels": [
            "Leviticus 16 sanctuary purgation underlies the whole argument; the kuppuru/Akitu purgation logic (see relig_013) is the ANE backdrop to blood presented to decontaminate the sancta",
            "The high-priestly entrance into the inner sanctum parallels ANE restricted access to the deity's innermost dwelling, here re-read as Christ's entrance into the heavenly presence",
            "Hittite zurki blood rites (Feder) as the purgation-direction analogue that frames blood as cleansing of holy things, not punishment of a victim"
        ],
        "interpretive_significance": "Even the explicitly atoning NT image operates by purification and presentation-of-life, not penal substitution -- 'God is the subject who provides, not the object placated.' Confidence: that Hebrews argues in the Yom Kippur/hatta't register and that hilasterion = kapporet is demonstrable. Moffitt's specific resurrection-as-presentation reading (the atoning moment is the ascension, not Calvary) is a strong inference, widely but not universally followed. See relig_013, relig_014, and method_007.",
        "period": "roman",
        "books": [
            {"book": "Heb", "chapter_start": 7, "chapter_end": 10},
            {"book": "Rom", "chapter_start": 3, "chapter_end": 3},
            {"book": "Lev", "chapter_start": 16, "chapter_end": 16}
        ],
        "key_references": ["Heb 7:16", "Heb 9:11-14", "Heb 9:22-26", "Heb 10:1-14", "Rom 3:25", "Lev 16:14-19"],
        "scholarly_sources": ["Moffitt, Atonement and the Logic of Resurrection (Brill)", "Moffitt, Rethinking the Atonement (Baker Academic)", "Rillera, Lamb of the Free (Cascade, 2024)", "Milgrom, Leviticus (Anchor Bible)"]
    },
]

LEGAL_COVENANT = [
    {
        "id": "legal_009",
        "title": "Covenant-Inauguration Blood Is Oath and Kinship Blood, Not Atonement Blood",
        "summary": "Exodus 24:3-8 is the backdrop of 'this is my blood of the covenant.' At Sinai the offerings are burnt and well-being offerings (explicitly non-purification); the blood is divided between altar and people to bind them into one covenantal body, and the rite culminates in a meal in God's presence. Covenant ratification by blood, oath, and shared meal is a distinct ANE institution from the purification offering.",
        "detail": "At Sinai the offerings are 'olot and shelamim (Exod 24:5), explicitly NOT hatta't; the blood is dashed on the altar and then on the people, binding the two parties into one covenantal body; the elders then 'beheld God, and ate and drank' (Exod 24:9-11). ANE covenant and treaty ratification by blood, shared meal, and oath is a demonstrably distinct institution from the purification offering. So the Last Supper words -- 'this is my blood of the covenant' (Mark 14:24; Matt 26:28; cf. 1 Cor 11:25; Luke 22:20 'new covenant,' invoking Jer 31:31-34) -- cite a covenant-making rite, and the meal context (bread eaten, cup shared) matches the shelamim/covenant-meal pattern. Matthew's wording 'for the forgiveness of sins' (Matt 26:28) invokes Jeremiah 31:34's new-covenant promise ('I will forgive their iniquity'), where forgiveness is a covenant benefit, not a sacrificial mechanism performed on Jesus.",
        "ane_parallels": [
            "ANE treaty and covenant ratification by blood rite, shared meal, and oath -- a recognized institution distinct from purification offering (cf. the karat berit, 'cut a covenant,' idiom; see legal_003)",
            "Mari and Amorite covenant practice (e.g., 'killing a donkey foal' to ratify a pact) as the household/treaty register of covenant blood",
            "ANE commensality establishing kinship and treaty bonds, so that eating in the deity's presence ratifies membership in his household (see relig_009)"
        ],
        "interpretive_significance": "The single most frequent NT image of Jesus's blood -- 'blood of the covenant,' the cup as koinonia -- is oath-and-kinship blood, not purgation blood; it binds a people into a covenantal body and is consummated in a meal, exactly the Exodus 24 pattern. Reading the Supper through Yom Kippur purgation misidentifies the institution being cited. Demonstrable. See legal_003 (covenant-cutting), relig_009 (meals as allegiance), and relig_020 (Passover).",
        "period": "exodus_conquest",
        "books": [
            {"book": "Exo", "chapter_start": 24, "chapter_end": 24},
            {"book": "Mrk", "chapter_start": 14, "chapter_end": 14},
            {"book": "Mat", "chapter_start": 26, "chapter_end": 26},
            {"book": "Luk", "chapter_start": 22, "chapter_end": 22},
            {"book": "1Co", "chapter_start": 11, "chapter_end": 11}
        ],
        "key_references": ["Exod 24:3-11", "Mark 14:24", "Matt 26:28", "Luke 22:20", "1 Cor 11:25", "Jer 31:31-34"],
        "scholarly_sources": ["Milgrom, Leviticus (Anchor Bible)", "Rillera, Lamb of the Free (Cascade, 2024)", "Hahn, Kinship by Covenant (Yale)", "Weinfeld, 'Covenant' studies"]
    },
]

DEATH_AFTERLIFE = [
    {
        "id": "death_008",
        "title": "Redemption as Extraction from the Household of Death: the go'el, Through Death, No Payment to the Captor",
        "summary": "Biblical ransom (ga'al, padah; Greek lytron) is a household office: the kinsman-redeemer (go'el) buys back persons and land fallen into bondage, at his own cost, and only kin may do it. Redemption is always FROM a captor or house (Egypt, Sheol, the domain of darkness) and no text ever depicts a payment made TO the captor. The captor holds power, not rights; his hold is broken, not bought out.",
        "detail": "The go'el is the kinsman with the right and duty to buy back persons and land (Lev 25:47-49; Ruth), at his own cost, and only kin may exercise it. The exodus formula names what one is redeemed from as a house: 'redeemed from the house of slavery (beit avadim), from the hand of Pharaoh' (Deut 7:8; Exod 13:3, 14) -- and no text depicts any payment to Pharaoh. The Sheol texts extend the grammar to the final captor: 'I will ransom them from the hand of Sheol; I will redeem them from Death' (Hos 13:14); 'no man can give God a kofer for his brother... but God will ransom my soul from the hand of Sheol' (Ps 49:7-9, 15) -- again nothing paid to Sheol. Biblical ransom therefore requires a captivity, a real cost to the redeemer, and a redeemer with kinship standing; it does not require a recipient. The NT names the captor and states the kinship requirement: 'since the children share in flesh and blood, he himself likewise partook of the same things, that THROUGH DEATH he might destroy the one who has the power of death, that is, the devil, and deliver those who through fear of death were subject to lifelong slavery' (Heb 2:14-15); the completed movement is household transfer, 'delivered from the domain of darkness and transferred into the kingdom of his beloved Son, in whom we have redemption' (Col 1:13-14). 'The soul that sins shall die' (Ezek 18:4; Gen 2:17) is honored, not waived: the ransom is not exemption from death but release on the far side of it, the captives freed through death because the kinsman went first and broke the holding power from inside (2 Cor 5:14; Rom 6:3-9; 1 Cor 15:20-26; Rev 20:14).",
        "ane_parallels": [
            "ANE kinsman-redemption and debt-slavery release: the go'el buying back enslaved kin and forfeited land, with the redeemer bearing the cost",
            "Mesopotamian royal debt-release edicts (anduraru / misharum): bondage cancelled by a sovereign act that frees captives without compensating the holder",
            "The exodus paradigm of liberation from a 'house of slavery' with no ransom paid to the oppressor -- redemption as rescue from a power, not a transaction with it"
        ],
        "interpretive_significance": "Biblical ransom excludes exactly one thing: penalty-payment to a creditor -- whether Satan (who holds power but no rights) or the Father (who is the redeemer, not the claimant). Gregory of Nazianzus (Oration 45.22) already poses the 'to whom was the blood offered?' question, rejects payment to the Evil One and to the Father alike, and concludes the Father receives the economy without being its creditor: recipient-less ransom is the grammar of the texts and an answer from inside the tradition's first centuries.\n\nConfidence (flag when retrieved): the household ransom grammar -- redemption from a power, real cost to the kinsman, no payment to any captor in any text -- is demonstrable. The recipient question itself has been contested since the patristic period (payment to Satan, to the Father, or no recipient); the corpus adopts the recipient-less, through-death reading as the best available account, since no biblical ransom text names a recipient and the go'el grammar requires none -- held as best available, not beyond revision. See cosmo_015 (death as the universal inheritance) and method_007.",
        "period": "exodus_conquest",
        "books": [
            {"book": "Lev", "chapter_start": 25, "chapter_end": 25},
            {"book": "Deu", "chapter_start": 7, "chapter_end": 7},
            {"book": "Hos", "chapter_start": 13, "chapter_end": 13},
            {"book": "Psa", "chapter_start": 49, "chapter_end": 49},
            {"book": "Mrk", "chapter_start": 10, "chapter_end": 10},
            {"book": "Heb", "chapter_start": 2, "chapter_end": 2},
            {"book": "Col", "chapter_start": 1, "chapter_end": 1}
        ],
        "key_references": ["Lev 25:47-49", "Deut 7:8", "Hos 13:14", "Ps 49:7-9", "Ps 49:15", "Mark 10:45", "1 Tim 2:6", "Heb 2:14-15", "Col 1:13-14", "1 Cor 15:20-26"],
        "scholarly_sources": ["Rillera, Lamb of the Free (Cascade, 2024)", "Aulen, Christus Victor", "Gregory of Nazianzus, Oration 45.22", "Levine, In the Presence of the Lord (go'el/kofer)"]
    },
]

GENDER_FAMILY = [
    {
        "id": "gender_008",
        "title": "Marriage as Covenant in Household Law, Not Indissoluble Sacrament",
        "summary": "In the composition-era world marriage is a covenant (berit) within household law (bet av) -- bride-price, betrothal, the joining of two households -- meant for lifelong permanence yet legally dissolvable (Deut 24). It is not the metaphysically indissoluble sacrament systematized in twelfth-century canon law. The category is covenant-within-household-law, not a sacramental ontology that cannot be undone.",
        "detail": "Marriage is named a covenant: 'the wife of your youth... your companion and the wife of your covenant' (Mal 2:14; cf. Prov 2:17 'the covenant of her God'; Ezek 16:8, God spreading his garment and entering covenant). It is embedded in the patriarchal household (bet av): mohar (bride-price), betrothal, and the joining of households. Crucially, the Torah assumes and REGULATES its dissolution -- the certificate of divorce (Deut 24:1-4) and the release provisions for a neglected wife (Exod 21:10-11). Jesus conducts the entire Matthew 19 / Mark 10 debate inside Torah household law: he engages Deut 24, tightens the grounds, and presses back to the creational intent of Genesis 2 ('the two shall become one flesh,' 'what God has joined together, let no one separate') -- he does not assert a sacramental metaphysics. The overlay being dated is marriage as one of seven sacraments conferring an ontologically indissoluble bond, systematized in twelfth-century canon law (Lombard, Gratian) and dogmatized later at Trent.",
        "ane_parallels": [
            "ANE marriage contracts (Nuzi, Old Babylonian, and the Jewish Elephantine papyri) document marriage as a household-legal covenant with bride-price, dowry, and explicit divorce clauses",
            "The patriarchal household (bet av) as the legal and economic frame within which marriage joins two estates (see gender_001, gender_002)",
            "ANE covenant grammar generally: a berit is a binding relationship with stipulations and sanctions, meant to endure but operating within law, not metaphysics"
        ],
        "interpretive_significance": "Reading marriage as covenant-within-household-law (not sacrament) keeps the biblical texts coherent: permanence is covenantal fidelity ('I hate divorce,' Mal 2:16; 'let no one separate,' Matt 19:6) within a household-legal institution -- not an ontological indissolubility the texts never assert and whose regulated exceptions they plainly provide. This is a dating note, not an attack: the sacramental-indissoluble reading is a twelfth-century development, located in its century and weighed against the composition-era context (see method_006). See gender_001 (marriage as covenant and economic transaction) and gender_002 (the bet av).",
        "period": "patriarchal",
        "books": [
            {"book": "Gen", "chapter_start": 2, "chapter_end": 2},
            {"book": "Deu", "chapter_start": 24, "chapter_end": 24},
            {"book": "Mal", "chapter_start": 2, "chapter_end": 2},
            {"book": "Mat", "chapter_start": 19, "chapter_end": 19},
            {"book": "Mrk", "chapter_start": 10, "chapter_end": 10}
        ],
        "key_references": ["Gen 2:24", "Mal 2:14-16", "Prov 2:17", "Ezek 16:8", "Deut 24:1-4", "Exod 21:10-11", "Matt 19:3-9", "Mark 10:2-12", "1 Cor 7:10-15"],
        "scholarly_sources": ["Hugenberger, Marriage as a Covenant (Brill)", "Instone-Brewer, Divorce and Remarriage in the Bible (Eerdmans)", "Schloen, The House of the Father as Fact and Symbol"]
    },
]

COSMOLOGY = [
    {
        "id": "cosmo_015",
        "title": "Original Sin: Inherited Mortality (Ancestral Sin) vs. Augustinian Inherited Guilt",
        "summary": "The composition-era reading inherits from Adam mortality and the reign of death -- the Eastern 'ancestral sin' -- not transmitted guilt. Augustinian inherited guilt rests partly on the Latin in quo misrendering of Romans 5:12's Greek eph' ho ('because'), and the federal 'covenant of works' reading of Eden is later still. Ezekiel individualizes culpability: 'the son shall not bear the iniquity of the father.'",
        "detail": "Romans 5:12 in Greek ends 'death spread to all because (eph' ho) all sinned.' The Old Latin and Vulgate rendered eph' ho as in quo, 'in whom,' making all humanity sin IN Adam and so share his guilt; Augustine, with limited Greek, built the doctrine of transmitted GUILT on this reading. The Greek-reading East developed instead 'ancestral sin' (propatorikon hamartema): from Adam we inherit mortality, corruption, and a weakened nature subject to death -- but not his guilt. The biblical witness individualizes culpability directly: 'the soul that sins shall die... the son shall not bear the iniquity of the father' (Ezek 18:4, 20). What Romans 5 actually emphasizes is the REIGN of death: 'death reigned from Adam to Moses' (5:14), 'in Adam all die' (1 Cor 15:21-22) -- the universal inheritance is the captor death, defeated by the kinsman who enters it (see death_008), rather than a birth-guilt requiring penal satisfaction. The further overlay -- Eden read as a 'covenant of works' with Adam as imputed federal head -- is sixteenth-to-seventeenth-century federal theology (crystallized at Westminster); the word berit does not appear in Genesis 2-3, and Hosea 6:7 ('like Adam they transgressed the covenant') is textually and exegetically debated.",
        "ane_parallels": [
            "ANE corporate-personality and household solidarity: the house shares the head's status and fate, the substrate for 'in Adam' read as corporate participation rather than forensic guilt-imputation (see social_007)",
            "Hebrew corporate ontology, in which a people is a body with a head, displaced in later Western reading by Greco-Roman individualism (so the 'body of sin' becomes one's own limbs rather than a household under a head)",
            "The ANE pattern of inherited condition (mortality, bondage) rather than inherited legal guilt as the natural frame for Adamic solidarity"
        ],
        "interpretive_significance": "This pairs with the ransom frame: humanity's universal inheritance is death-the-captor (Rom 5:14; 1 Cor 15:21-22), which Christ defeats by entering it -- not a forensic birth-guilt that must be penally satisfied. Dating note, not attack: inherited mortality / ancestral sin is composition-era; inherited forensic guilt is the Latin-driven Western overlay (Augustine, 4th-5th c.), and the covenant-of-works reading is later still (see method_006). Confidence: the eph' ho / in quo philology and Ezekiel's individualizing of culpability are demonstrable; the precise content of 'ancestral sin' across the fathers admits variation. See cosmo_013 (Hebrew anthropology), social_007 (corporate personality), and death_008.",
        "period": "patriarchal",
        "books": [
            {"book": "Gen", "chapter_start": 2, "chapter_end": 3},
            {"book": "Ezk", "chapter_start": 18, "chapter_end": 18},
            {"book": "Rom", "chapter_start": 5, "chapter_end": 6},
            {"book": "1Co", "chapter_start": 15, "chapter_end": 15}
        ],
        "key_references": ["Gen 2:17", "Gen 3:17-19", "Ezek 18:4", "Ezek 18:20", "Rom 5:12-21", "Rom 6:6", "1 Cor 15:21-22"],
        "scholarly_sources": ["Heiser, The Unseen Realm", "Rillera, Lamb of the Free (Cascade, 2024)", "N. T. Wright, The Resurrection of the Son of God", "Meyendorff, Byzantine Theology (ancestral sin)", "Wolff, Anthropology of the Old Testament"]
    },
]

METHODOLOGY = [
    {
        "id": "method_005",
        "title": "One Author, Two Testaments: Inspiration, Coherence, and Fulfillment",
        "summary": "This corpus operates under a stated axiom: Scripture is inspired by God, and inspiration entails coherence. One Author speaks in Leviticus and in Hebrews, at Sinai and at the Supper; there are no contradictions and no errors in the text, only questions interpreters have not yet resolved. The only relation the corpus recognizes between the testaments is fulfillment -- never correction, never discard.",
        "detail": "Two consequences govern usage. FIRST, the Levitical cult is a real, divinely-designed institution that really accomplished what God designed it to accomplish: the forgiveness formula is true ('the priest shall effect purgation for him, and he shall be forgiven,' Lev 4:31), the purgation really maintained the divine residence, and the shelamim meal really constituted fellowship in God's presence. Its provisionality is internal to its design, in the NT's own architectural language -- the law had 'a shadow of the good things to come' (Heb 10:1; Col 2:17), and a shadow is cast by the reality it anticipates: anticipation by design, never decoration after the fact. The cult points past itself because its Author built it to; that is fulfillment honoring the institution, not its dismissal. SECOND, vocabulary: where an entry speaks of the 'image,' 'register,' or 'typology' of a NT text, it means the invocation of a real, divinely-instituted practice and its God-given grammar; 'mere metaphor' is not on the table, and any reading that treats the OT systems as literary decoration the NT writers raided loosely has already violated the axiom. Certainty about every solution is not required and is not claimed; doubt about the unity of the text is excluded. This stands with the historic rule of faith: the councils, creeds, and confessions stand (see method_004); what ANE recovery changes is resolution, not the confession.",
        "ane_parallels": [
            "Canonical priority guardrail (method_003): when the canon connects two texts, that intra-biblical connection controls over any external parallel -- the textual expression of one-Author coherence",
            "The typology / metaphor / functional-identity distinction (method_003): 'fulfillment' and 'image' name real correspondence and real invocation, not loose illustration",
            "Recovery-not-novelty (method_004): the creeds stand; ANE context raises the resolution of what was always in the text"
        ],
        "interpretive_significance": "This entry states the corpus's mode so its claims are read rightly. The corpus may record a tension as unresolved; it never attributes error to the text and never frames the NT as acting against the OT. For readers who do not share the inspiration axiom, the same conclusions about NT competence stand independently on historical grounds: first-century Jewish writers steeped in the cult demonstrably distinguish its institutions (Passover is never confused with the purification offering; covenant blood is never confused with purgation blood). The axiom and the history converge. See method_006 (the proximity standard) and method_007 (atonement as a worked example).",
        "period": "patriarchal",
        "books": ["Gen", "Exo", "Lev", "Isa", "Mat", "Luk", "Heb", "2Ti", "2Pe"],
        "chapter_start": None,
        "chapter_end": None,
        "key_references": ["Matt 5:17", "Luke 24:27", "Luke 24:44", "Heb 10:1", "Col 2:17", "Lev 4:31", "2 Tim 3:16", "2 Pet 1:20-21"],
        "scholarly_sources": ["Childs, Biblical Theology of the Old and New Testaments", "Beale, The Temple and the Church's Mission", "Rillera, Lamb of the Free (Cascade, 2024)"]
    },
    {
        "id": "method_006",
        "title": "The Standard of Evidence: Composition-Context Controls; Later Frameworks Are Dated, Not Attacked",
        "summary": "The governing principle is proximity: a text means what it meant in the world where it was written, and the weight of evidence runs with the date of composition. Later interpretive frameworks are located in their centuries and weighed accordingly, not read back as the text's native sense. A text taken out of context is a pretext. Lateness is not falsity; it is location.",
        "detail": "For material composed from Sinai to the Second Temple, the controlling witnesses are the Hebrew text, the contemporaneous ANE comparanda, the LXX, Second-Temple reception, and first-century usage; every century of distance adds datable layers that must be dated and weighed, not assumed to be the native sense. A set of frameworks, each datable, illustrates the rule: penal substitution as a formulated mechanism (16th-17th c.); Anselmian satisfaction (1098, feudal-honor register, explicitly NOT penal); the covenant-of-works reading of Eden (16th-17th c. federal theology); inherited GUILT as formulated by Augustine (4th-5th c.), resting partly on the Latin in quo misrendering of Rom 5:12; the immortal-soul anthropology that displaces bodily resurrection (Platonic import, progressive from the 2nd c.); marriage as an indissoluble sacrament rather than a covenant within household law (systematized 12th c.); the individualist reading of corporate-body language (Greco-Roman anthropology displacing Hebrew corporate ontology); the flattening of the divine-council worldview into either monism or mere metaphor (post-first-century, against Deut 32:8; Ps 82); and the English word 'atonement' itself, a 16th-century coinage laid over kipper, whose composition-era sense is purgation. The modern comparative recovery (Milgrom and the ANE evidence) is not another late layer of the same kind; it is the retrieval of the composition-era context itself, which is why it controls.\n\nTHE THROUGHLINE -- why these travel together. They are not independent hobby-horses; one drift produces them all. Flatten the divine council and swap Hebrew corporate/household ontology for Greco-Roman individualism, and the dominoes fall in one direction: the hostile powers become metaphors (gutting Christus Victor and ransom); the hope migrates from corporate bodily resurrection to the individual soul in heaven; sin becomes an individual's inherited guilt-ledger rather than a household under the reign of death; marriage becomes an individual sacramental bond rather than a covenant joining households; and the terminus is an individual, forensic, penalty-transfer atonement in place of a household rescued from death through participation. Flatten the council and individualize the person, and penal substitution becomes natural. Recovering the council and the corporate frame is what makes the older readings legible again.",
        "ane_parallels": [
            "Sandmel, 'Parallelomania' (JBL 1962): the foundational warning that the direction and weight of any parallel must be argued from the evidence, not assumed",
            "Deuteronomy 32:8-9: the DSS (4QDeut-j) and LXX 'sons of God' preserved against the Masoretic 'sons of Israel' -- the textbook case of a later flattening corrected by older evidence",
            "The explicate-vs-impose and canonical-priority guardrails (method_003): context is supplied to prevent the pretext, not to license novelty"
        ],
        "interpretive_significance": "Stated without hostility: this corpus is not an attack on penal substitution or on Reformed theology; it dates interpretive frameworks against the context in which Scripture was written. Later thought is not precluded; it is located. Where a later framework stands in opposition to the demonstrable composition-era context, that opposition is named as what it is, and the framework must be met on its own resources -- by composition-era-through-first-century evidence, which the corpus will weigh on its tiers (see method_002) like any other. This entry is the corpus's evidential rule; method_007 applies it to atonement, and cosmo_013, cosmo_015, gender_008, and the divine-council entries (cosmo_008, cosmo_011) are the worked cases.",
        "period": "patriarchal",
        "books": ["Gen", "Deu", "Psa", "Isa", "Rom", "1Co", "Heb"],
        "chapter_start": None,
        "chapter_end": None,
        "key_references": ["Deut 32:8-9", "Ps 82:1-8", "Rom 5:12", "Gen 2:7", "1 Cor 15:42-54", "Mal 2:14", "Lev 16:30"],
        "scholarly_sources": ["Milgrom, Leviticus 1-16 (Anchor Bible)", "Sandmel, 'Parallelomania' (JBL 81, 1962)", "Heiser, The Unseen Realm", "Walton, Ancient Near Eastern Thought and the Old Testament", "Rillera, Lamb of the Free (Cascade, 2024)"]
    },
    {
        "id": "method_007",
        "title": "Atonement as a Test Case: Non-Penal Cult Grammar and the Late Formulation of Penal Substitution",
        "summary": "Applied to atonement, the proximity standard yields a clear result: the Levitical and ANE evidence provide no grounding for penal substitution -- no offering punishes the animal, death is not the operative element, and no sin is transferred to anything that reaches the altar. Penal substitution as a formulated mechanism is a late development; if it has a biblical grounding it must be demonstrated from outside the sacrificial cult, and that burden rests on its proponents.",
        "detail": "No ecumenical creed or council defines a mechanism of atonement: the Nicene-Constantinopolitan confession says 'for us and for our salvation... was crucified' and stops. The first-millennium working accounts were ransom and Christus Victor (the devil's dominion broken, captives freed), recapitulation (Irenaeus), participation and healing (Athanasius), and sacrifice read in the purgative register this corpus documents. Substitutionary and curse-bearing language exists in the fathers (Justin on Gal 3:13, Athanasius on the debt of death, Chrysostom and Cyril on 2 Cor 5:21); the hardest case is Eusebius (Dem. Ev. 10.1 on Isa 53: a penalty 'which we owed... the price of our souls'). Even there the mechanism is absent: the inflictors Eusebius names are human violence and the law's curse (the double agency of Acts 2:23), not the Father administering punishment; he glosses his own sentence as ransom ('the price of our souls,' the lytron register); and he never states the defining claim that the Father's retributive justice required satisfaction by penalty judicially inflicted on a substitute. Anselm's satisfaction theory (Cur Deus Homo, 1098) is the first systematic mechanism, and it is explicitly NOT penal -- it turns on aut poena aut satisfactio, satisfaction offered precisely INSTEAD of punishment, in a feudal-honor register. The penal conversion of satisfaction is the Reformers' work, systematized in Protestant scholasticism (16th-17th c.).",
        "ane_parallels": [
            "ANE penalty/fate-transfer rituals (substitute king, namburbi) existed and were non-sacrificial; the altar cult declines to use them (see relig_016) -- the historical pivot of the non-penal case",
            "The molk environment (child offered to purchase favor), the nearest ANE analogue to penal satisfaction, is exactly what the Torah outlaws (see relig_017)",
            "Hittite zurki blood rites (Feder) as the purgation-direction analogue to the hatta't, confirming blood's function as cleansing of holy things rather than punishment of a victim"
        ],
        "interpretive_significance": "Confident-but-flagged. The HISTORICAL conclusion -- no creed defines a mechanism; Anselm is satisfaction-not-penal; the penal formulation is 16th-17th c. -- is demonstrable and not contested the way exegesis is. This does not make penal substitution false: late formulation is not falsity, and the doctrine must be argued exegetically like any other; recovering the biblical, ANE, and early-church context is the return journey, not novelty (method_004), and the creeds stand (method_005). Genuinely contested, and to be flagged when retrieved: the direction of the hatta't purgation (Gane's reverse-flow alternative -- still non-penal), Isaiah 53:10's 'asham register, and the ransom recipient question (see death_008). Texts pressed into penal-substitution service (Rom 8:3; 2 Cor 5:21; Gal 3:13; Isa 53) carry their participatory, apocalyptic, and burden-bearing senses. See method_006 (the evidential rule this applies) and relig_012-021.",
        "period": "patriarchal",
        "books": ["Lev", "Isa", "Rom", "2Co", "Gal", "Heb", "1Pe"],
        "chapter_start": None,
        "chapter_end": None,
        "key_references": ["Isa 53:4-12", "Rom 3:25", "Rom 8:3", "2 Cor 5:21", "Gal 3:13", "Heb 9:11-14", "1 Pet 2:21-25"],
        "scholarly_sources": ["Rillera, Lamb of the Free (Cascade, 2024)", "Aulen, Christus Victor", "Anselm, Cur Deus Homo (1098)", "Eusebius, Demonstratio Evangelica 10.1", "Moffitt, Rethinking the Atonement (Baker Academic)"]
    },
]


NEW_BY_FILE = {
    "02_religious_practices.json": RELIGIOUS_PRACTICES,
    "04_legal_covenant.json": LEGAL_COVENANT,
    "10_death_afterlife.json": DEATH_AFTERLIFE,
    "11_gender_family.json": GENDER_FAMILY,
    "01_cosmology_worldview.json": COSMOLOGY,
    "13_methodology.json": METHODOLOGY,
}


# ---------------------------------------------------------------------------
# Augmentations to existing entries (idempotent via sentinel checks).
# ---------------------------------------------------------------------------

def augment_relig_008(entry: dict) -> bool:
    """Add the Hittite/Ebla elimination-rite parallels and a cross-reference."""
    changed = False
    sentinel = "Hittite Ritual of Ashella"
    parallels = entry.get("ane_parallels", [])
    if not any(sentinel in p for p in parallels):
        parallels.extend([
            "Hittite Ritual of Ashella: during a plague in the army camp, adorned rams are driven toward enemy territory carrying the plague away",
            "Hittite Rituals of Ambazzi (a mouse carries off the evil to the steppe) and Uhhamuwa (a crowned ram driven away to remove plague)",
            "Ebla and later Syrian goat-dispatch rites for purging a city, attested as early as the third millennium -- transfer-and-banishment as a recognized ANE genre distinct from altar sacrifice",
        ])
        entry["ane_parallels"] = parallels
        changed = True
    interp = entry.get("interpretive_significance", "") or ""
    note = ("\n\nIn ANE terms the scapegoat belongs to the elimination/disposal genre "
            "(transfer-and-banishment), which is formally distinct from altar sacrifice: "
            "the one unambiguous sin-transfer rite in the Torah is non-sacrificial, and the "
            "sacrificial rites involve no transfer (see relig_015, relig_016).")
    if "elimination/disposal genre" not in interp:
        entry["interpretive_significance"] = interp + note
        changed = True
    sources = entry.get("scholarly_sources", [])
    if not any("Disposal of Impurity" in s for s in sources):
        sources.append("Wright, The Disposal of Impurity (Hittite and Mesopotamian elimination rites)")
        entry["scholarly_sources"] = sources
        changed = True
    return changed


def augment_cosmo_013(entry: dict) -> bool:
    """Add the immortal-soul-vs-bodily-resurrection dating note to the soul entry."""
    interp = entry.get("interpretive_significance", "") or ""
    if "immortal-soul anthropology" in interp:
        return False
    note = ("\n\nDating note (see method_006): the immortal-soul anthropology that makes a "
            "disembodied soul the true self and its survival the hope of the faithful is a "
            "Platonic import, progressive from the second century onward (LXX nephesh->psyche, "
            "Philo, the Alexandrians, Augustine). The composition-era hope is BODILY resurrection "
            "(Dan 12:2; Isa 26:19; 1 Cor 15), and immortality is something 'put on' at the "
            "resurrection (1 Cor 15:53-54), not an innate property -- 'God alone has immortality' "
            "(1 Tim 6:16). Confidence flag: the governing hope is resurrection, but the texts do "
            "imply some intermediate-state consciousness (Luke 23:43; Phil 1:23; Rev 6:9) and "
            "Second-Temple Judaism developed beliefs about the soul's survival (Wisdom of Solomon); "
            "so the careful claim is that Platonic soul-as-true-self DISPLACING resurrection is the "
            "late overlay, not that no intermediate consciousness exists.")
    entry["interpretive_significance"] = interp + note
    refs = entry.get("key_references", [])
    for r in ["1 Cor 15:53-54", "1 Tim 6:16", "Dan 12:2"]:
        if r not in refs:
            refs.append(r)
    entry["key_references"] = refs
    return True


AUGMENTATIONS = {
    "02_religious_practices.json": {"relig_008": augment_relig_008},
    "01_cosmology_worldview.json": {"cosmo_013": augment_cosmo_013},
}


# ---------------------------------------------------------------------------
# Merge + load.
# ---------------------------------------------------------------------------

INLINE_THRESHOLD = 384  # max inline length observed for scalar-only arrays in the corpus


def _enc(obj, lvl):
    """Serialize matching the corpus house style: a container with any nested
    container is multiline; an all-scalar container inlines only if short."""
    pad = "  " * lvl
    pad1 = "  " * (lvl + 1)
    if isinstance(obj, (dict, list)):
        if not obj:
            return "{}" if isinstance(obj, dict) else "[]"
        children = list(obj.values()) if isinstance(obj, dict) else obj
        has_container = any(isinstance(x, (dict, list)) for x in children)
        if not has_container and len(json.dumps(obj, ensure_ascii=False)) <= INLINE_THRESHOLD:
            return json.dumps(obj, ensure_ascii=False)
        if isinstance(obj, dict):
            body = ",\n".join(f"{pad1}{json.dumps(k, ensure_ascii=False)}: {_enc(v, lvl + 1)}" for k, v in obj.items())
            return "{\n" + body + "\n" + pad + "}"
        body = ",\n".join(f"{pad1}{_enc(v, lvl + 1)}" for v in obj)
        return "[\n" + body + "\n" + pad + "]"
    return json.dumps(obj, ensure_ascii=False)


def _entry_spans(text, open_idx, close_idx):
    """Yield (start, end) spans of each top-level {...} object inside an array,
    skipping braces that occur inside JSON strings."""
    i = open_idx + 1
    depth = 0
    start = None
    in_str = False
    esc = False
    while i < close_idx:
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                if depth == 0:
                    start = i
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    yield (start, i + 1)
        i += 1


def merge_json() -> list[str]:
    """Splice changes into the dimension JSON files WITHOUT reserializing untouched
    entries: each unchanged entry keeps its exact original bytes; changed/new entries
    are rendered with the house-style encoder. Idempotent by id and by augmentation
    sentinel."""
    touched = []
    files = set(NEW_BY_FILE) | set(AUGMENTATIONS)
    for fname in sorted(files):
        path = ANE_DIR / fname
        text = path.read_text(encoding="utf-8")

        arr_kw = text.index('"entries"')
        open_idx = text.index("[", arr_kw)
        # matching close bracket for the entries array (string-aware)
        depth = 0
        in_str = esc = False
        j = open_idx
        while j < len(text):
            ch = text[j]
            if in_str:
                esc = (ch == "\\") and not esc
                if ch == '"' and not esc:
                    in_str = False
            else:
                if ch == '"':
                    in_str = True
                elif ch == "[":
                    depth += 1
                elif ch == "]":
                    depth -= 1
                    if depth == 0:
                        break
            j += 1
        close_idx = j

        blocks = [text[s:e] for s, e in _entry_spans(text, open_idx, close_idx)]
        existing_ids = {json.loads(b)["id"] for b in blocks}
        file_changed = False

        # augment existing entries in place (rewrite only that block)
        for eid, fn in AUGMENTATIONS.get(fname, {}).items():
            for k, b in enumerate(blocks):
                obj = json.loads(b)
                if obj.get("id") != eid:
                    continue
                if fn(obj):
                    blocks[k] = _enc(obj, 2)
                    file_changed = True
                    print(f"  ~ {fname}: augmented {eid}")
                else:
                    print(f"  = {fname}: {eid} augmentation already applied, skipping")
                break

        # append new entries
        for new_entry in NEW_BY_FILE.get(fname, []):
            if new_entry["id"] in existing_ids:
                print(f"  = {fname}: {new_entry['id']} already present, skipping")
                continue
            blocks.append(_enc(new_entry, 2))
            existing_ids.add(new_entry["id"])
            file_changed = True
            print(f"  + {fname}: added {new_entry['id']} -- {new_entry['title']}")

        if file_changed:
            inner = "\n    " + ",\n    ".join(blocks) + "\n  "
            new_text = text[:open_idx + 1] + inner + text[close_idx:]
            json.loads(new_text)  # validate before writing
            path.write_text(new_text, encoding="utf-8")
            touched.append(fname)
    return touched


def load_db(touched: list[str]):
    """INSERT OR REPLACE the changed dimension files into the existing DB."""
    from study_bible_mcp.parsers.ane_context import parse_ane_context_file

    if not DB_PATH.exists():
        print(f"  ! DB not found at {DB_PATH}; skipping DB load (JSON updated, rebuild when ready)")
        return
    conn = sqlite3.connect(str(DB_PATH))
    n_entries = n_maps = 0
    for fname in touched:
        for entry, book_mappings in parse_ane_context_file(ANE_DIR / fname):
            conn.execute(
                """INSERT OR REPLACE INTO ane_entries
                   (id, dimension, dimension_label, title, summary, detail,
                    ane_parallels, interpretive_significance, period, period_label,
                    key_references, scholarly_sources)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (entry["id"], entry["dimension"], entry["dimension_label"], entry["title"],
                 entry["summary"], entry.get("detail"), entry.get("ane_parallels"),
                 entry.get("interpretive_significance"), entry.get("period"),
                 entry.get("period_label"), entry.get("key_references"),
                 entry.get("scholarly_sources")),
            )
            n_entries += 1
            # Delete-then-insert: INSERT OR REPLACE cannot dedupe rows whose
            # chapter_start is NULL (NULL != NULL in a composite PK), so clear
            # this entry's mappings first to keep re-runs idempotent.
            conn.execute("DELETE FROM ane_book_mappings WHERE entry_id=?", (entry["id"],))
            for bm in book_mappings:
                conn.execute(
                    """INSERT OR REPLACE INTO ane_book_mappings
                       (entry_id, book, chapter_start, chapter_end) VALUES (?,?,?,?)""",
                    (bm["entry_id"], bm["book"], bm.get("chapter_start"), bm.get("chapter_end")),
                )
                n_maps += 1
    conn.commit()
    conn.close()
    print(f"  loaded {n_entries} entries / {n_maps} book mappings from {len(touched)} file(s) into {DB_PATH.name}")


if __name__ == "__main__":
    print("Merging Lamb-of-the-Free entries into data/ane_context/ ...")
    touched = merge_json()
    if not touched:
        print("No JSON changes (already ingested).")
    else:
        print(f"Touched: {', '.join(touched)}")
    print("Loading into database ...")
    load_db(touched if touched else list(set(NEW_BY_FILE) | set(AUGMENTATIONS)))
    print("Done.")
