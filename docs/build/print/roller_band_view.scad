// Close-up of the take-away roller, axle, rubber bands and hook blocks (docs/build/roller-band.png).
use </home/user/sortbuddy/docs/build/print/sortbuddy_parts.scad>
$fn = 48;
// slide coordinates: floor bottom z=0, card plane z=2, axle at x=40, z=11
module band(y) color("red") {
    for (x = [38.6, 41.4]) translate([x, y, -0.7]) cylinder(d = 1.2, h = 11 + 2.7 + 0.7);
    translate([38.6, y, -0.7]) rotate([0, 90, 0]) cylinder(d = 1.2, h = 2.8);          // under the hook block
    translate([38.6, y, 13.3]) rotate([0, 90, 0]) cylinder(d = 1.2, h = 2.8);          // over the axle
}
intersection() {
    color("plum") slide_takeaway_lite();
    translate([0, -20, -30]) cube([95, 110, 60]);
}
color("black") translate([40, -11, 11]) rotate([0, 0, 90]) translate([0, 0, -2 * cos(22.5)]) takeaway_axle();
for (i = [0 : 2]) color("lightblue") translate([40, 3.5 + i * 21.2, 11]) rotate([-90, 0, 0]) takeaway_roller(21);
color("dimgray") translate([40, 36.5, -17]) rotate([90, 0, 0]) belt_wheel(false);
band(-7.6);
band(77.6);
