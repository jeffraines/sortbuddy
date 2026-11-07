// Exploded view of the feeder, built from the real parts in sortbuddy_parts.scad.
//   openscad --render=false --imgsize=2000,1400 -o feeder-exploded.png feeder_exploded.scad
use <sortbuddy_parts.scad>
$fn = 64;
E = 1;                       // explode factor: 0 = assembled

LABELS = false;
module lbl(s, p, size = 5) { if (LABELS)
    color("black") translate(p) rotate([55, 0, 25]) linear_extrude(0.4) text(s, size = size, halign = "center");
}
module guide(a, b) { color([0.4, 0.4, 0.4]) hull() { translate(a) sphere(0.5); translate(b) sphere(0.5); } }

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
lbl("THROAT STRIP", [103 + 25 * E, 35, 62]);
lbl("chamfer faces the wall", [103 + 25 * E, 35, 54], 3.5);
lbl("gap = 1 card + a bit", [103 + 25 * E, 35, -6], 3.5);

// bracket + motor + wheel, dropped down
dz = -55 * E;
translate([0, 0, dz]) {
    color([0.85, 0.5, 0.35]) translate([20, 42, -50]) multmatrix([[1, 0, 0, 0], [0, 0, 1, 0], [0, 1, 0, 0]]) bracket();
    // 28BYJ-48 stand-in
    color([0.75, 0.75, 0.8]) {
        translate([67, 42, -22]) rotate([-90, 0, 0]) cylinder(d = 28, h = 19);          // body behind the plate
        translate([67, 41, -22]) rotate([-90, 0, 0]) linear_extrude(1)
            hull() for (dx = [-17.5, 17.5]) translate([dx, 0]) circle(d = 7);            // ears on the slot side
        translate([67 - 8.5, 42, -22 - 17.5]) cube([17, 17, 6]);                          // wire box (down)
        translate([67, 42, -14]) rotate([90, 0, 0]) cylinder(d = 5, h = 10);              // shaft
    }
    lbl("MOTOR BRACKET", [40, 75, -40]);
    lbl("28BYJ-48", [100, 75, -30]);
}
guide([35, 50.5, 0], [35, 50.5, dz]);
guide([85, 50.5, 0], [85, 50.5, dz]);

// wheel: slides onto the shaft, comes up through the slot
color([0.3, 0.3, 0.3]) translate([67, 32.5 - 35 * E, dz - 14]) rotate([-90, 0, 0]) wheel(40);
color([0.15, 0.15, 0.15]) translate([67, 34 - 35 * E, dz - 14]) rotate([-90, 0, 0]) difference() {
    cylinder(d = 38.6, h = 5); translate([0, 0, -1]) cylinder(d = 36, h = 7);            // rubber bands
}
lbl("WHEEL + rubber bands", [67, -35 * E - 10, dz - 45]);
guide([67, 32.5 - 35 * E + 8, dz - 14], [67, 32, dz - 14]);
lbl("wheel pokes ~1 mm above the floor", [67, 35, -12], 3.5);

// slide: the hopper's lip rests 20 mm onto its floor
color([0.7, 0.6, 0.9]) translate([106 + 70 * E, 0, -2 - 10 * E]) slide();
lbl("SLIDE", [190 + 70 * E, 35, 40]);
lbl("lip rests 20 mm on the slide floor", [150 + 40 * E, 35, -30], 3.5);
