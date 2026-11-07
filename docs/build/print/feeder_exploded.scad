// Exploded view of the feeder, built from the real parts in sortbuddy_parts.scad.
//   openscad --render=false --imgsize=2000,1400 -o feeder-exploded.png feeder_exploded.scad
use <sortbuddy_parts.scad>
$fn = 64;
E = 1;                       // explode factor: 0 = assembled
VIEW = "full";               // or "motor", "throat", "bracket" for the close-ups

LABELS = false;
module lbl(s, p, size = 5) { if (LABELS)
    color("black") translate(p) rotate([55, 0, 25]) linear_extrude(0.4) text(s, size = size, halign = "center");
}
module guide(a, b) { color([0.4, 0.4, 0.4]) hull() { translate(a) sphere(0.5); translate(b) sphere(0.5); } }


// ---- fasteners (M3): screw along +axis from its head, washer, hex nut
module m3_screw(len) { color([0.2, 0.2, 0.25]) { cylinder(d = 5.5, h = 2); translate([0, 0, 2]) cylinder(d = 3, h = len); } }
module m3_washer() { color([0.75, 0.75, 0.78]) difference() { cylinder(d = 7, h = 0.6); translate([0, 0, -1]) cylinder(d = 3.2, h = 3); } }
module m3_nut() { color([0.6, 0.6, 0.65]) difference() { cylinder(d = 6.35, h = 2.4, $fn = 6); translate([0, 0, -1]) cylinder(d = 3, h = 5); } }

if (VIEW == "full") {
// hopper (light version) at the origin
color([0.95, 0.75, 0.2]) hopper(2.4);
lbl("HOPPER", [53, 35, 72]);

// stack weight
color([0.55, 0.75, 0.95]) translate([10, 4, 20 + 70 * E]) weight();
lbl("STACK WEIGHT  (+ coins)", [53, 35, 115 * E + 20]);
guide([53, 35, 22], [53, 35, 20 + 70 * E]);

// a few cards in the hopper (face up)
color([0.9, 0.9, 0.9]) for (i = [0 : 5]) translate([8, 3.5, 5.2 + i * 0.8]) cube([88, 63, 0.3]);

// throat strip on the front wall's outside
color([0.6, 0.85, 0.6]) translate([103.4 + 25 * E, 0, 5.5]) multmatrix([[0, 0, 1, 0], [1, 0, 0, 0], [0, 1, 0, 0]]) throat();
for (y = [17, 53]) {
    translate([99 - 14 * E, y, 34]) rotate([0, 90, 0]) m3_screw(10);                 // head inside the hopper
    translate([105 + 37 * E, y, 34]) rotate([0, 90, 0]) m3_washer();
    translate([105.6 + 45 * E, y, 34]) rotate([0, 90, 0]) m3_nut();
}
lbl("THROAT STRIP", [103 + 25 * E, 35, 62]);
lbl("chamfer faces the wall", [103 + 25 * E, 35, 54], 3.5);
lbl("gap = 1 card + a bit", [103 + 25 * E, 35, -6], 3.5);

// bracket + motor + wheel, dropped down
dz = -55 * E;
translate([0, 0, dz]) {
    color([0.85, 0.5, 0.35]) translate([100, 42, -50]) rotate([0, 0, 180]) rotate([90, 0, 0]) bracket();   // the real, rigid placement
    // 28BYJ-48 stand-in
    color([0.75, 0.75, 0.8]) {
        translate([67, 42, -22]) rotate([-90, 0, 0]) cylinder(d = 28, h = 19);          // body behind the plate
        translate([67, 41, -22]) rotate([-90, 0, 0]) linear_extrude(1)
            hull() for (dx = [-17.5, 17.5]) translate([dx, 0]) circle(d = 7);            // ears on the slot side
        translate([67 - 8.5, 42, -22 - 17.5]) cube([17, 17, 6]);                          // wire box (down)
        translate([67, 42, -14]) rotate([90, 0, 0]) cylinder(d = 5, h = 10);              // shaft
    }
    // ear screws: head on the ear (wheel) side, washer + nut on the back
    for (dx = [-17.5, 17.5]) {
        translate([67 + dx, 39 - 22 * E, -22]) rotate([-90, 0, 0]) m3_screw(8);
        translate([67 + dx, 45 + 14 * E, -22]) rotate([-90, 0, 0]) m3_washer();
        translate([67 + dx, 45.6 + 22 * E, -22]) rotate([-90, 0, 0]) m3_nut();
    }
    // bracket-to-floor screws, from below through the flange
    for (x = [35, 85]) {
        translate([x, 50.5, -6.2 - 18 * E]) m3_screw(8);
        translate([x, 50.5, -4.2 - 12 * E]) m3_washer();
        translate([x, 50.5, -3.6 - 8 * E]) m3_washer();
    }
    lbl("MOTOR BRACKET", [40, 75, -40]);
    lbl("28BYJ-48", [100, 75, -30]);
}
guide([35, 50.5, 0], [35, 50.5, dz]);
guide([85, 50.5, 0], [85, 50.5, dz]);

// wheel: slides onto the shaft, comes up through the slot
color([0.3, 0.3, 0.3]) translate([67, 28.5 - 35 * E, dz - 14]) rotate([-90, 0, 0]) wheel_spaced(40);
color([0.15, 0.15, 0.15]) translate([67, 30 - 35 * E, dz - 14]) rotate([-90, 0, 0]) difference() {
    cylinder(d = 38.6, h = 5); translate([0, 0, -1]) cylinder(d = 36, h = 7);            // rubber bands
}
lbl("WHEEL + rubber bands", [67, -35 * E - 10, dz - 45]);
guide([67, 28.5 - 35 * E + 11, dz - 14], [67, 28.5, dz - 14]);
lbl("wheel pokes ~1 mm above the floor", [67, 35, -12], 3.5);

// slide: the hopper's lip rests 20 mm onto its floor
color([0.7, 0.6, 0.9]) translate([106 + 70 * E, 0, -2 - 10 * E]) slide();
lbl("SLIDE", [190 + 70 * E, 35, 40]);
lbl("lip rests 20 mm on the slide floor", [150 + 40 * E, 35, -30], 3.5);

}

// ---- close-up details, shown alone with VIEW = "motor" / "throat" / "bracket"
module motor_standin_unused() {
    color([0.75, 0.75, 0.8]) {
        translate([67, 42, -22]) rotate([-90, 0, 0]) cylinder(d = 28, h = 19);
        translate([67, 41, -22]) rotate([-90, 0, 0]) linear_extrude(1)
            hull() for (dx = [-17.5, 17.5]) translate([dx, 0]) circle(d = 7);
        translate([67 - 8.5, 42, -22 - 17.5]) cube([17, 17, 6]);
        translate([67, 42, -14]) rotate([90, 0, 0]) cylinder(d = 5, h = 10);
    }
}
if (VIEW == "motor") {
    color([0.75, 0.75, 0.8]) cube([1, 16, 16]);                                                 // motor ear
    color([0.85, 0.5, 0.35]) translate([10, 0, 0]) cube([3, 16, 16]);                            // bracket plate
    translate([-18, 8, 8]) rotate([0, 90, 0]) m3_screw(8);
    translate([24, 8, 8]) rotate([0, 90, 0]) m3_washer();
    translate([32, 8, 8]) rotate([0, 90, 0]) m3_nut();
    color([0.4, 0.4, 0.4]) translate([-22, 8, 8]) rotate([0, 90, 0]) cylinder(d = 0.6, h = 60);
}
if (VIEW == "throat") {
    color([0.95, 0.75, 0.2]) translate([0, 0, 0]) cube([2.4, 16, 16]);                                        // front wall piece
    color([0.6, 0.85, 0.6]) translate([14, 0, 0]) cube([1.6, 16, 16]);                                        // strip
    translate([-16, 8, 8]) rotate([0, 90, 0]) m3_screw(10);
    translate([26, 8, 8]) rotate([0, 90, 0]) m3_washer();
    translate([34, 8, 8]) rotate([0, 90, 0]) m3_nut();
    color([0.4, 0.4, 0.4]) translate([-20, 8, 8]) rotate([0, 90, 0]) cylinder(d = 0.6, h = 60);
}
if (VIEW == "bracket") {
    color([0.95, 0.75, 0.2]) translate([0, 0, 0]) cube([24, 16, 5]);                                         // hopper floor piece
    color([0.85, 0.5, 0.35]) translate([0, 0, -14]) cube([24, 16, 3]);                                       // bracket flange
    translate([12, 8, -40]) m3_screw(8);
    translate([12, 8, -27]) m3_washer();
    translate([12, 8, -22]) m3_washer();
    color([0.4, 0.4, 0.4]) translate([12, 8, -44]) cylinder(d = 0.6, h = 46);
}
