// SortBuddy: 3D-printed parts that replace the foam ones where precision matters.
//
//   openscad -D 'part="wheel"' -o wheel.stl sortbuddy_parts.scad
//   parts: wheel, wheel_big, bracket, throat, flap, hopper, hopper_light,
//          slide, weight, servo_mount
//
// All in mm. Letters match foam-template.pdf (W wheel, Q bracket, T strip, G flap,
// hopper = P1-P5 in one piece, slide = A + B, weight = S).
// PLA, 0.2 mm layers, 3 walls, 30% infill. Print every part flat as exported,
// no supports.

part = "wheel";
$fn = 96;
fit = 0.15;              // extra clearance per side for holes; raise if too tight

// ---------------------------------------------------------------- 28BYJ-48
SHAFT_D = 5;             // round part of the shaft
SHAFT_FLATS = 3;         // across the two flats
FLAT_LEN = 6;            // flats run this far back from the shaft tip
BODY_D = 28;
SHAFT_OFF = 8;           // shaft centre is 8 mm off the body centre
EAR_PITCH = 35;          // mounting-hole spacing
EAR_HOLE = 4.2;
WIRE_BOX_W = 18;         // the plastic wire cover on the side of the body
WIRE_BOX_R = 17.5;       // how far it sticks out from the body centre

// ---------------------------------------------------------------- W: feed wheel
// Two flanges with a recess between them for rubber bands (or a 3 mm O-ring).
// The bands should end up roughly flush with the flanges, so the band surface
// is what grips the card. Bore: flats for the first 6 mm from the outer face,
// round behind that, so it goes all the way on.
module wheel(d = 40, w = 8) {
    recess = 1.4;
    flange = 1.2;
    difference() {
        union() {
            cylinder(d = d, h = flange);
            translate([0, 0, flange]) cylinder(d = d - 2 * recess, h = w - 2 * flange);
            translate([0, 0, w - flange]) cylinder(d = d, h = flange);
        }
        // round bore over the whole width
        translate([0, 0, -1]) cylinder(d = SHAFT_D + 2 * fit, h = w + 2);
    }
    // two flat keys filling the bore's sides over the outer FLAT_LEN (z=0 is the outer face)
    intersection() {
        cylinder(d = SHAFT_D + 2 * fit, h = FLAT_LEN);
        for (s = [-1, 1])
            translate([s * (SHAFT_FLATS / 2 + fit + 5), 0, FLAT_LEN / 2])
                cube([10, 10, FLAT_LEN], center = true);
    }
}

// ---------------------------------------------------------------- Q: motor bracket
// Hangs under the hopper floor (top flange glued or screwed under the floor,
// plate's flat face on the blue line on P1, toward the wheel slot). Motor ears
// go on the slot side, body through the hole. Slotted holes give +-2 mm of
// height adjustment, which sets how far the wheel pokes up through the floor.
module bracket() {
    L = 80; H = 50; t = 3;
    flange_w = 14;
    adj = 2;
    bx = 47; bz = 28;             // body centre in plate coords (as on the template)
    module slot2d(d, len) {       // vertical slot
        hull() for (s = [-1, 1]) translate([0, s * len / 2]) circle(d = d);
    }
    // plate lies flat on the bed (z = thickness); flange stands up from its top edge
    difference() {
        union() {
            cube([L, H, t]);
            translate([0, H - t, 0]) cube([L, t, flange_w]);       // top flange
            for (x = [4, L - 7])                                      // gussets
                translate([x, H - t, 0])
                    rotate([90, 0, 90]) linear_extrude(3)
                        polygon([[0, 0], [-12, 0], [0, 10]]);
        }
        translate([0, 0, -1]) linear_extrude(t + 2) {
            translate([bx, bz]) slot2d(BODY_D + 2 * 0.6, 2 * adj);
            translate([bx - WIRE_BOX_W / 2 - 0.5, bz - WIRE_BOX_R - adj - 0.5])
                square([WIRE_BOX_W + 1, WIRE_BOX_R + adj]);
            for (dx = [-EAR_PITCH / 2, EAR_PITCH / 2])
                translate([bx + dx, bz]) slot2d(EAR_HOLE + 2 * fit, 2 * adj);
        }
        // two screw holes in the flange (optional: glue works too)
        for (x = [15, L - 15])
            translate([x, H + 1, t + (flange_w - t) / 2]) rotate([90, 0, 0])
                cylinder(d = 3.4, h = t + 2);
        // shaft-height mark: a small notch on each side edge, level with the shaft
        for (x = [-0.01, L - 1.2]) translate([x, bz + SHAFT_OFF - 0.4, -1]) cube([1.21, 0.8, t + 2]);
    }
}

// ---------------------------------------------------------------- T: throat strip
// Rigid, dead-straight bottom edge. Slots (instead of the template's holes)
// combine with the front wall's slots for a wide adjustment range. The
// chamfer goes on the HOPPER side at the bottom, so the next card is guided
// back instead of snagging.
module throat() {
    L = 70; H = 40; t = 1.6;
    difference() {
        cube([L, H, t]);
        for (x = [17, 53]) translate([x, 0, -1]) hull()
            for (y = [24, 34]) translate([0, y, 0]) cylinder(d = 3.4, h = t + 2);
        // lead-in chamfer along the bottom edge, on the face that touches the bed
        // (the face on the bed goes against the front wall, i.e. faces the hopper)
        translate([-1, 0, 0]) rotate([90, 0, 90]) linear_extrude(L + 2)
            polygon([[-1, -1], [2, -1], [-1, 2]]);
    }
    // a grip tab so you can nudge it while tuning
    translate([L / 2 - 6, H - 4, t]) cube([12, 4, 2]);
}

// ---------------------------------------------------------------- G: gate flap
// Thin and stiff, with a channel the servo horn lies in (glue or two tiny
// zip ties through the holes). The bottom edge is the one that stops the card.
module flap() {
    L = 55; H = 32; t = 1.6;
    rib = 1.6; ch_w = 7.5;
    difference() {
        union() {
            cube([L, H, t]);
            // horn channel: two ribs, ch_w apart, centred on y = 23.5 (template's blue box)
            for (s = [-1, 1])
                translate([3, 23.5 + s * (ch_w / 2 + rib / 2) - rib / 2, t]) cube([22, rib, 1.8]);
        }
        for (x = [7, 20]) translate([x, 23.5, -1]) {   // zip-tie holes either side of the channel
            translate([0, ch_w / 2 + rib + 1.4, 0]) cylinder(d = 2, h = 5, $fn = 24);
            translate([0, -ch_w / 2 - rib - 1.4, 0]) cylinder(d = 2, h = 5, $fn = 24);
        }
    }
}

// ---------------------------------------------------------------- P1-P5: hopper in one piece
// Same layout as the foam hopper (x = along the travel direction): back wall
// 0-5, stack 5-101, front wall 101-106, lip 106-126. Floor 5 thick so the
// printed bracket and wheel sit exactly as on the template. Print standing on
// its floor, no supports: the only overhang is the 70 mm bridge over the
// throat, and a little sag there doesn't matter because strip T sets the gap.
// Underneath: two 2.5 mm pilot holes for M3 screws through the bracket's
// flange (or just glue the flange there).
module hopper(wall = 5) {
    // Inner faces stay where the template puts them (stack 5-101, channel 0-70)
    // whatever the wall thickness, so the wheel and bracket still line up.
    L = 126; CHW = 70; floor_t = 5; Hh = 60;
    gap = 3;                       // front wall's bottom above the floor top
    back = 5; front = 101;         // inner faces of the back and front walls
    x0 = back - wall;
    difference() {
        union() {
            translate([x0, 0, 0]) cube([L - x0, CHW, floor_t]);             // floor + lip
            for (y = [-wall, CHW]) translate([x0, y, 0]) cube([front + wall - x0, wall, Hh]);  // sides
            translate([x0, 0, 0]) cube([wall, CHW, Hh]);                     // back wall
            translate([front, 0, floor_t + gap]) cube([wall, CHW, Hh - floor_t - gap]);  // front wall
        }
        translate([49, 28, -1]) cube([36, 14, floor_t + 2]);              // wheel slot
        for (y = [17, 53])                                                 // slots for strip T screws
            translate([front - 1, y, 0]) hull()
                for (z = [floor_t + gap + 19 + 1.75, floor_t + gap + 33 - 1.75])
                    translate([0, 0, z]) rotate([0, 90, 0]) cylinder(d = 3.5, h = wall + 2, $fn = 24);
        for (x = [35, 85]) translate([x, 50.5, -1]) cylinder(d = 2.5, h = 4 + 1, $fn = 24);  // bracket screws
        for (y = [-wall - 1, CHW - 1])                                     // finger notches to grab the stack
            translate([53, y, Hh]) rotate([-90, 0, 0]) cylinder(r = 15, h = wall + 2);
        // bracket position mark on the underside: a shallow groove along the slot-side face line
        translate([20, 42 - 0.3, -0.01]) cube([80, 0.6, 0.4]);
    }
}

// ---------------------------------------------------------------- A + B: slide in one piece
// Floor 0-175 along the travel direction; walls end at 160 so the last 15 mm
// of floor slides between upper-hood panels C1 and C2 onto the acrylic.
// Walls are 5 mm like the foam, so they stay flush with panels C for
// joiners J. The floor is only 2 mm (the foam's 5 mm was just board
// thickness), so the step down onto the window is small, and its far end is
// bevelled to a thin edge. Print floor down; the top of the floor is the card
// path, so turn on ironing (top surfaces) if your slicer has it.
module slide() {
    L = 175; CHW = 70; wall = 5; floor_t = 2; Hw = 30; wall_end = 160;
    bevel = 10;
    difference() {
        union() {
            cube([L, CHW, floor_t]);
            for (y = [-wall, CHW]) translate([0, y, 0]) cube([wall_end, wall, Hw]);
        }
        // bevel the top of the floor's far end down to 0.6 mm
        translate([L - bevel, -1, floor_t]) rotate([0, atan((floor_t - 0.6) / bevel), 0])
            cube([bevel + 5, CHW + 2, 5]);
        // lead-in chamfers on the inside top edges of the walls at the hopper end
        for (y = [0, CHW]) translate([-1, y, Hw]) rotate([45, 0, 0]) cube([12, 2, 2], center = true);
    }
}

// ---------------------------------------------------------------- S: stack weight
// Sits on the top card. Fill the tray with coins, nuts or washers until it
// weighs 30-50 g in total. Flat side (bed side) goes down on the cards.
module weight() {
    L = 86; W = 62; t = 2; rim = 6;
    difference() {
        union() {
            cube([L, W, t]);
            translate([0, 0, t]) difference() {
                cube([L, W, rim]);
                translate([2, 2, -1]) cube([L - 4, W - 4, rim + 2]);
            }
            translate([L / 2 - 8, W / 2 - 2, t]) cube([16, 4, rim + 6]);   // lift handle
        }
        translate([L / 2 - 5, W / 2 - 3, t + rim]) cube([10, 6, 3.5]);     // finger hole in the handle
    }
}

// ---------------------------------------------------------------- servo mount (C1 gate, N sorter)
// MG90S: body 22.8 x 12.2, ears 32.3 long with screw holes 27.8 apart.
// Glue the plate on the OUTSIDE of panel C1, its hole over C1's servo cutout
// (enlarge the foam cutout a little if needed). Drop the servo in from
// outside, ears on the plate, and fix it with the screws that came with it.
// Print 3: one for the gate, two for the sorter flap later (replaces N).
module servo_mount() {
    L = 46; W = 24; t = 3;
    body = [23.2, 12.6];           // MG90S body + clearance
    ear_pitch = 27.8;
    difference() {
        translate([-L / 2, -W / 2, 0]) cube([L, W, t]);
        translate([-body[0] / 2, -body[1] / 2, -1]) cube([body[0], body[1], t + 2]);
        for (s = [-1, 1]) translate([s * ear_pitch / 2, 0, -1]) cylinder(d = 1.8, h = t + 2, $fn = 24);
    }
    // two stiffening ribs on the servo side; the flat bed side is the one glued to the foam
    for (s = [-1, 1]) translate([-L / 2, s > 0 ? W / 2 - 1.2 : -W / 2, t]) cube([L, 1.2, 2]);
}

if (part == "wheel") wheel(40);
else if (part == "wheel_big") wheel(42);
else if (part == "bracket") bracket();
else if (part == "throat") throat();
else if (part == "flap") flap();
else if (part == "hopper") hopper();
else if (part == "hopper_light") hopper(2.4);   // thin walls: less plastic, same inside
else if (part == "slide") slide();
else if (part == "weight") weight();
else if (part == "servo_mount") servo_mount();
