// SortBuddy elevator feeder: concept model (real dimensions, simplified parts).
// Cards stand FACE DOWN in a box; a lead screw raises the floor so the top card
// always sits at PICK. A pick head (A: soft roller, B: suction swing arm) moves
// the top card's front edge over the separation ramp into the shared exit
// rollers, which pull it out. The head mounts on two rails on top of the box
// and is swappable.
//   openscad -D 'PART="all"' ...   PART: all | section | <part name> (for export)
//   HEAD = "roller" | "suction"
PART = "all";
HEAD = "roller";
CARDS = 150;                  // cards loaded in the picture (max ~580: floor skirts reach the base)
$fn = 28;

CARD = [88, 63, 0.31];        // card: length (direction of travel), width, thickness
IX = 91; IY = 66;             // box inside: card + 1.5 mm each side
W = 2.4;                      // wall
PICK = 200;                   // top surface of the top card (fixed)
SPLIT = 170;                  // the box prints in two parts: 0..SPLIT, SPLIT..top
TOP = PICK + 6;               // top of the box walls
LS = [-14, IY / 2];           // lead screw axis (outside the back wall)
PLAT_T = 4;                   // lift floor thickness
plat_z = PICK - CARDS * CARD[2] - PLAT_T;   // underside of the lift floor
NIP_X = 112; NIP_Z = PICK + 1.5;            // exit roller nip
RAMP_X0 = IX + W;                           // separation ramp starts at the front wall

// ---------------------------------------------------------------- box (lower + upper)
module box_shell(z0, z1, front_top) {
    difference() {
        translate([-W, -W, z0]) cube([IX + 2 * W, IY + 2 * W, z1 - z0]);
        translate([0, 0, z0 - 1]) cube([IX, IY, z1 - z0 + 2]);
        // lift slot in the back wall
        translate([-W - 1, IY / 2 - 6, max(z0, 6) ]) cube([W + 2, 12, z1 - max(z0, 6) + 1]);
        // front wall stops below the pick line: the top card leaves over it
        if (front_top < z1) translate([IX - 1, -1, front_top]) cube([W + 2, IY + 2, z1]);
        // windows in the side walls to see the stack (lower part only)
        // peaked tops (45 degrees): nothing flat to sag when printed upright
        if (z0 == 0) for (y = [-W - 1, IY - 1]) for (zz = [24, 96]) translate([15, y, zz]) rotate([90, 0, 0]) mirror([0, 0, 1])
            linear_extrude(W + 2) polygon([[0, 0], [60, 0], [60, 30], [30, 60], [0, 30]]);
    }
}
module box_lower() {
    box_shell(0, SPLIT, 999);
    translate([-W, -W, 0]) cube([IX + 2 * W, IY + 2 * W, 3]);          // base
    for (x = [-W, IX + W - 8], y = [-W, IY + W - 8]) translate([x, y, -24]) cube([8, 8, 24]);   // feet
    // lead-screw base plate with the lift motor under it
    translate([LS[0] - 14, LS[1] - 20, 0]) cube([14 - W, 40, 3]);
}
module box_upper() {
    box_shell(SPLIT, TOP, PICK - 1.0);
    // head rails on top of the side walls (heads screw on here)
    for (y = [-W - 4, IY]) translate([-W, y, TOP]) difference() {
        cube([IX + 2 * W, W + 4, 4]);
        for (x = [10, 40, 70]) translate([x, (W + 4) / 2, -1]) cylinder(d = 3.2, h = 6);
    }
    // top bushing for the lead screw
    translate([LS[0] - 8, LS[1] - 8, TOP - 6]) difference() { cube([8 + 0, 16, 6]); translate([8, 8, -1]) cylinder(d = 8.6, h = 8); }
}
// separation ramp: rubber-faced incline on top of the front wall; the top card
// is driven up it, the cards under it stop against it
module sep_ramp() {
    translate([RAMP_X0, 0, PICK - 1.0]) rotate([90, 0, 0]) translate([0, 0, -IY])
        linear_extrude(IY) polygon([[0, 0], [8, 0], [8, 3.2], [0, 0.6]]);
}
module sep_pad() color("hotpink") translate([RAMP_X0, 0, PICK - 0.4]) rotate([90, 0, 0]) translate([0, 0, -IY])
    linear_extrude(IY) polygon([[0, 0], [8, 2.6], [8, 3.0], [0, 0.4]]);

// ---------------------------------------------------------------- elevator
module lift_floor() {
    translate([0.6, 0.6, plat_z]) cube([IX - 1.2, IY - 1.2, PLAT_T]);
    for (y = [0.6, IY - 3.6]) translate([0.6, y, plat_z - 12]) cube([IX - 1.2, 3, 12]);   // skirts keep it level
    // arm through the back-wall slot to the lead-screw nut block
    translate([LS[0] - 8, IY / 2 - 5, plat_z - 12]) cube([8 + 8, 10, 12 + PLAT_T]);
    translate([LS[0] - 9, LS[1] - 9, plat_z - 12]) difference() { cube([18, 18, 12]); translate([9, 9, -1]) cylinder(d = 8.4, h = 14); }
}
module lead_screw() translate([LS[0], LS[1], 2]) cylinder(d = 8, h = TOP - 2);
module lift_motor() translate([LS[0], LS[1], -21]) { cylinder(d = 28, h = 19); translate([-8.5, -31, 0]) cube([17, 17, 19]); }
module cards() for (i = [0 : 3 : CARDS - 1]) translate([1.5, 1.5, plat_z + PLAT_T + i * CARD[2]]) cube([CARD[0], CARD[1], CARD[2] * 3 - 0.02]);
module top_card() translate([1.5, 1.5, PICK - CARD[2]]) cube(CARD);

// ---------------------------------------------------------------- shared exit rollers
module exit_rollers() {
    translate([NIP_X, 6, NIP_Z - 10]) rotate([-90, 0, 0]) cylinder(d = 20, h = IY - 12);   // driven, rubber
    translate([NIP_X, 6, NIP_Z + 8]) rotate([-90, 0, 0]) cylinder(d = 16, h = IY - 12);    // idler, soft
}
module exit_frame() {
    for (y = [-W - 3, IY + W]) translate([IX + W, y, NIP_Z - 24]) difference() {
        cube([30, 3, 40]);
        translate([NIP_X - IX - W, -1, 14]) rotate([-90, 0, 0]) cylinder(d = 5, h = 5);
        translate([NIP_X - IX - W - 2.5, -1, 28]) cube([5, 5, 10]);                           // idler slot
    }
    translate([IX + W, -W - 3, NIP_Z - 26]) cube([30, IY + 2 * W + 6, 2]);
}
module exit_motor() translate([NIP_X, IY + W + 3, NIP_Z - 10]) rotate([-90, 0, 0]) { cylinder(d = 28, h = 19); }
module exit_chute() translate([IX + W + 30, 6, NIP_Z - 3]) rotate([0, 15, 0]) cube([70, IY - 12, 2]);

// ---------------------------------------------------------------- head A: soft roller on a sprung arm
module head_roller() {
    piv = [8, PICK + 34];
    rc = [72, PICK + 10];                                    // roller centre: roller (d 20) rests on the top card
    for (y = [-W - 4, IY + 1]) translate([0, y, TOP + 4]) cube([18, 3, piv[1] - TOP + 2]);    // pivot posts on the rails
    translate([piv[0], -W - 4, piv[1]]) rotate([-90, 0, 0]) cylinder(d = 4, h = IY + 2 * W + 8);
    // arm (two plates) from pivot to roller
    for (y = [IY / 2 - 18, IY / 2 + 15]) hull() {
        translate([piv[0], y, piv[1]]) rotate([-90, 0, 0]) cylinder(d = 10, h = 3);
        translate([rc[0], y, rc[1]]) rotate([-90, 0, 0]) cylinder(d = 10, h = 3);
    }
}
module head_roller_soft() color("hotpink") translate([72, IY / 2 - 15, PICK + 10]) rotate([-90, 0, 0]) cylinder(d = 20, h = 30);
module head_roller_motor() translate([72, IY / 2 + 18, PICK + 10]) rotate([-90, 0, 0]) cylinder(d = 28, h = 19);
// microswitch on the outside of the pivot post; the arm's tail presses it when
// the stack has lifted the roller to the pick height, which stops the lift
module head_switch() translate([2, IY + 4, PICK + 22]) cube([12, 6, 7]);

// ---------------------------------------------------------------- head B: suction cup on a servo swing arm
module head_suction() {
    piv = [44, PICK + 40];
    for (y = [-W - 4, IY + 1]) translate([30, y, TOP + 4]) cube([24, 3, piv[1] - TOP + 4]);
    translate([piv[0] - 11, IY / 2 - 6, piv[1] - 6]) cube([23, 12, 22]);                      // servo body
    hull() {                                                                                   // arm down to the cup
        translate([piv[0], IY / 2 - 2, piv[1]]) rotate([-90, 0, 0]) cylinder(d = 8, h = 4);
        translate([80, IY / 2 - 2, PICK + 10]) rotate([-90, 0, 0]) cylinder(d = 8, h = 4);
    }
    translate([80, IY / 2, PICK + 2]) cylinder(d = 4, h = 8);
}
module head_cup() color("hotpink") translate([80, IY / 2, PICK]) cylinder(d1 = 14, d2 = 6, h = 4);
module head_pump() { translate([20, IY + W + 6, TOP - 40]) cube([30, 22, 24]); translate([56, IY + W + 6, TOP - 34]) cube([18, 16, 18]); }

// ---------------------------------------------------------------- assembly
module scene() {
    color("gainsboro") box_lower();
    color("silver") box_upper();
    color("silver") sep_ramp(); sep_pad();
    color("lightseagreen") lift_floor();
    color("dimgray") lead_screw();
    color("slategray") lift_motor();
    color("white") cards();
    color("orange") top_card();
    color("darkgray") exit_rollers(); color("silver") exit_frame(); color("slategray") exit_motor();
    color("silver") exit_chute();
    if (HEAD == "roller") { color("lightsteelblue") head_roller(); head_roller_soft(); color("slategray") head_roller_motor(); color("gold") head_switch(); }
    if (HEAD == "suction") { color("lightsteelblue") head_suction(); head_cup(); color("slategray") head_pump(); }
}
if (PART == "all") scene();
if (PART == "section") intersection() { scene(); translate([-60, IY / 2 - 0.5, -40]) cube([260, 1, 300]); }
// single parts for export
if (PART == "box_lower") box_lower();
if (PART == "box_upper") box_upper();
if (PART == "sep_ramp") sep_ramp();
if (PART == "sep_pad") sep_pad();
if (PART == "lift_floor") lift_floor();
if (PART == "lead_screw") lead_screw();
if (PART == "lift_motor") lift_motor();
if (PART == "cards") cards();
if (PART == "top_card") top_card();
if (PART == "exit_rollers") exit_rollers();
if (PART == "exit_frame") exit_frame();
if (PART == "exit_motor") exit_motor();
if (PART == "exit_chute") exit_chute();
if (PART == "head_roller") head_roller();
if (PART == "head_roller_soft") head_roller_soft();
if (PART == "head_roller_motor") head_roller_motor();
if (PART == "head_switch") head_switch();
if (PART == "head_suction") head_suction();
if (PART == "head_cup") head_cup();
if (PART == "head_pump") head_pump();
if (PART == "cutaway") difference() { scene(); translate([-80, -40, -60]) cube([320, 40 + IY / 2, 360]); }
