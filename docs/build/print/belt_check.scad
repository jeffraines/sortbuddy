// Belt-drive assembly check: MODE="all" draws it; the other MODEs intersect two parts (empty = no collision).
use </home/user/sortbuddy/docs/build/print/sortbuddy_parts.scad>
$fn = 48;
MODE = "all";
TA = 146;
module hop() hopper(2.4);
module brk() translate([100, 42, -50]) rotate([0, 0, 180]) rotate([90, 0, 0]) bracket_lite();
module mot() {  // 28BYJ-48 stand-in: body behind the plate, ears, shaft, wire box
    translate([67, 42, -22]) rotate([-90, 0, 0]) cylinder(d = 28, h = 19);
    translate([67, 41, -22]) rotate([-90, 0, 0]) linear_extrude(1) hull() for (dx = [-17.5, 17.5]) translate([dx, 0]) circle(d = 7);
    translate([67 - 8.5, 42, -22 - 17.5]) cube([17, 17, 6]);
    translate([67, 39.5, -14]) rotate([-90, 0, 0]) cylinder(d = 9, h = 1.5);   // boss
}
module spc() translate([67, 39.5, -14]) rotate([90, 0, 0]) belt_spacer();
module fw()  translate([67, 36.5, -14]) rotate([90, 0, 0]) belt_wheel(true);
module sld() translate([106, 0, -2]) slide_takeaway_lite();
module tw()  translate([TA, 36.5, -19]) rotate([90, 0, 0]) belt_wheel(false);
module frm() translate([106, 0, -2]) belt_frame_installed();
module axl() translate([TA, 17, -19]) rotate([-90, 0, 0]) cylinder(d = 5, h = 25);
module belt() translate([0, 26.5, 0]) rotate([90, 0, 0]) linear_extrude(2.4) difference() {
    hull() { translate([67, -14]) circle(r = 12.4); translate([TA, -19]) circle(r = 12.4); }
    hull() { translate([67, -14]) circle(r = 11); translate([TA, -19]) circle(r = 11); }
}
if (MODE == "all") { color("gold") hop(); color("coral") brk(); color("silver") mot(); color("gray") spc(); color("dimgray") fw();
    color("plum") sld(); color("dimgray") tw(); color("orange") frm(); color("black") axl(); color("red") belt(); }
module X(a) { intersection() { children(0); children(1); } }
if (MODE == "belt_hop") X() { belt(); hop(); }
if (MODE == "belt_sld") X() { belt(); sld(); }
if (MODE == "belt_brk") X() { belt(); brk(); }
if (MODE == "belt_mot") X() { belt(); mot(); }
if (MODE == "belt_frm") X() { belt(); frm(); }
if (MODE == "fw_hop") X() { fw(); hop(); }
if (MODE == "fw_brk") X() { fw(); brk(); }
if (MODE == "fw_mot") X() { fw(); mot(); }
if (MODE == "tw_sld") X() { tw(); sld(); }
if (MODE == "tw_frm") X() { tw(); frm(); }
if (MODE == "sld_hop") X() { sld(); hop(); }
if (MODE == "frm_sld") X() { frm(); sld(); }
