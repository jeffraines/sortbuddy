// SortBuddy: 3D-printed parts that replace the foam ones where precision matters.
//
//   openscad -D 'part="wheel"' -o wheel.stl sortbuddy_parts.scad
//   parts: slide_takeaway, takeaway_bracket, takeaway_roller, takeaway_axle, hopper_frame, wheel, wheel_big, wheel_spaced, wheel_lite, bracket_lite, bracket, throat, flap, hopper, hopper_light,
//          slide, weight, servo_mount, camera_mount, lower_hood,
//          led_channel, led_channel_short, splice, joiner, joints (4 H + 2 J),
//          plate_E, plate_F, panel_D
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
    // Body centre in plate coords. 33 (not the template's 47): with the flange
    // under the floor pointing away from the slot, the part is turned so its
    // x runs backwards along the hopper, and 33 lands the motor under the
    // middle of the wheel slot (hopper x 67).
    bx = 33; bz = 28;
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
                cylinder(d = 3.8, h = t + 2);     // printed sideways: oversized so M3 passes
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


// Finger slots, one in each side wall facing each other, so the stack can be
// pinched and lifted out. 22 mm wide, centred on the stack (x 53), down to
// 5 mm above the floor: below that the walls stay whole, so the bottom card's
// edges never pass a gap while it is fed out.
module finger_slots(wall, CHW, floor_t, Hh) {
    for (y = [-wall - 1, CHW - 1]) translate([53, y, 0]) rotate([-90, 0, 0]) mirror([0, 1, 0])
        linear_extrude(wall + 2) hull() {
            translate([0, floor_t + 5 + 11]) circle(r = 11);
            translate([-11, Hh - 1]) square([22, 10]);
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
        finger_slots(wall, CHW, floor_t, Hh);                              // pinch the stack out from both sides
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

// ---------------------------------------------------------------- camera mount (E top, F bottom)
// For the 26 x 10.5 mm USB camera boards (HX3807, square M5 lens holder at
// one end, no mounting holes). The camera is held by its lens holder: it sits
// in a square pocket and its front rests on a thin lip, so the lens is
// centred on the plate's centre notches and square to it. The board itself
// floats just behind the plate inside low walls; a dab of hot glue on the
// walls (never on the lens) holds it. Open end of the walls = cable side.
// Dimensions read off the listing photos: if the holder doesn't go in, or
// rattles a lot, change CAM_HOLDER.
//   top camera (E): plate's flat front face down on E, lens over E's hole
//   bottom camera (F): flip it over, walls stand on F, lens looks up
CAM_HOLDER = [9.2, 9.6];   // lens-holder pocket (holder ~8.3 along the board x ~9 across) + clearance
module camera_mount() {
    t = 3; lip = 0.8; lens_hole = 7.4;
    board = [26, 10.5];
    to_far = 4.0;              // lens centre to the board's far (lens) end
    to_conn = board[0] - to_far;
    cl = 0.4; wt = 1.2; wh = 6;
    x0 = -to_conn - cl - wt - 3; x1 = to_far + cl + wt + 3;
    yh = board[1] / 2 + cl + wt + 3;
    difference() {
        union() {
            translate([x0, -yh, 0]) cube([x1 - x0, 2 * yh, t]);
            // walls round the board outline, open at the connector end
            translate([0, 0, t]) difference() {
                translate([-to_conn - cl - wt, -board[1] / 2 - cl - wt, 0])
                    cube([board[0] + 2 * cl + 2 * wt, board[1] + 2 * cl + 2 * wt, wh]);
                translate([-to_conn - cl, -board[1] / 2 - cl, -1])
                    cube([board[0] + 2 * cl, board[1] + 2 * cl, wh + 2]);
                translate([-to_conn - cl - wt - 1, -board[1] / 2 - cl, -1])
                    cube([wt + 2, board[1] + 2 * cl, wh + 2]);           // cable exit
            }
        }
        translate([-CAM_HOLDER[0] / 2, -CAM_HOLDER[1] / 2, lip]) cube([CAM_HOLDER[0], CAM_HOLDER[1], t]);
        translate([0, 0, -1]) cylinder(d = lens_hole, h = t + 2);
        // window for the connector (it sits on the lens side of the board)
        translate([-to_conn - cl, -board[1] / 2 - cl, -1]) cube([8, board[1] + 2 * cl, t + 2]);
        // centre notches on all four edges: line them up with the + on plate E / F
        for (p = [[x0, 0], [x1, 0], [0, -yh], [0, yh]])
            translate([p[0], p[1], -1]) rotate([0, 0, 45]) cube([2, 2, t + 2], center = true);
    }
}

// ---------------------------------------------------------------- lower hood (D1 + D2 + F, H splices) in one piece
// x = along the channel, 0 = slide end, the acrylic window spans x 0-130 and
// y -5..75 (80 x 130 x 2 mm, as on the template). Prints standing on its
// floor, no supports: the ledge under the window is a 45 degree chamfer.
//   * the acrylic drops into the top between two side rims, flush with them,
//     and rests on a 4 mm ledge all round. Nothing above it at the gate end,
//     so cards leave over a clean edge; a 1 mm stop at the slide end.
//   * upper hood panels C sit on the acrylic's side edges, right above
//     the rims, as before.
//   * camera_mount stands upside down (walls down) in the recess on the
//     floor: lens 130 mm below the window, centred where the card stops
//     (x 67), connector toward the slide end, cable out of the hole there.
//   * notches on the rim tops: x 15 (slide floor ends), 67 (camera), 115 (gate).
//   * closed on all sides, unlike the foam: no room light from below.
// Print it in a light colour (white / light grey): a dark inside gives dark
// corners and harsher glare.
ACRYLIC_T = 2;
module lower_hood() {
    wall = 2; cl = 0.3; ledge = 4; fl = 3;
    y0 = -5 - cl; y1 = 75 + cl;             // acrylic edges + clearance
    zb = fl + 9 + 130;                       // acrylic underside (mount is ~9 tall)
    difference() {
        union() {
            translate([-wall, y0 - wall, 0]) cube([130 + wall, y1 - y0 + 2 * wall, zb]);
            for (y = [y0 - wall, y1]) translate([-wall, y, zb]) cube([130 + wall, wall, ACRYLIC_T]);  // side rims
            translate([-wall, y0 - wall, zb]) cube([wall, y1 - y0 + 2 * wall, 1]);                    // slide-end stop
        }
        // inside, with the chamfered ledge under the window
        hull() {
            translate([0, y0, fl]) cube([128, y1 - y0, zb - ledge - fl]);
            translate([ledge - 1, y0 + ledge, zb - 0.01]) cube([128 - 2 * ledge + 2, y1 - y0 - 2 * ledge, 0.02]);
        }
        translate([0, y0, zb]) cube([140, y1 - y0, 10]);                                           // acrylic pocket
        translate([-wall - 1, 30, fl]) cube([wall + 2, 10, 8]);                                     // cable hole
        // camera_mount locator: its wall outline (29.2 x 13.7) + clearance, lens at (67, 35)
        translate([67 - 23.6 - cl, 35 - 6.85 - cl, fl - 0.8]) cube([29.2 + 2 * cl, 13.7 + 2 * cl, 1]);
        // alignment notches on the rim tops
        for (x = [15, 67, 115], y = [y0 - wall, y1 + wall])
            translate([x, y, zb + ACRYLIC_T]) rotate([0, 45, 0]) cube([1.6, 2 * wall + 2, 1.6], center = true);
    }
}

// ---------------------------------------------------------------- LED diffuser channel
// For an 8 mm LED strip. The strip sticks to the channel's floor; a strip of
// printer paper (10 mm wide) slides into the grooves near the top from one
// end, about 5 mm in front of the LEDs, so they glow evenly instead of
// showing bright dots. Flat back: hot glue or double-sided tape onto the foam.
// Ends are open for the wires. led_channel(120) for the long hood walls,
// led_channel(60) for short runs.
LED_STRIP_W = 8;
module led_channel(len = 120) {
    w = LED_STRIP_W + 0.6; fl = 1.2; wt = 1.6; h = 8.5;
    groove_z = fl + 7; gd = 0.8; gh = 0.7;
    difference() {
        cube([len, w + 2 * wt, h]);
        translate([-1, wt, fl]) cube([len + 2, w, h]);
        for (y = [wt - gd, wt + w - 0.01])                       // paper grooves
            translate([-1, y, groove_z]) cube([len + 2, gd + 0.01, gh]);
    }
}

// ---------------------------------------------------------------- H splice, J joiner
// Thin flat plates, glued on the OUTSIDE across a joint (hot glue or
// double-sided tape). Side notches mark the joint line.
//   H (x4): 50 x 42, across the upper/lower hood seam at the window edge;
//     the notches go on the window, upper panel C above, lower panel D below.
//   J (x2): 40 x 25, from a slide wall onto upper-hood panel C.
module joint_plate(w, h, line_at, horizontal_line) {
    t = 1.6;
    difference() {
        cube([w, h, t]);
        for (e = [0, 1])
            if (horizontal_line) translate([e * w, line_at, -1]) rotate([0, 0, 45]) cube([2, 2, t + 2], center = true);
            else translate([line_at, e * h, -1]) rotate([0, 0, 45]) cube([2, 2, t + 2], center = true);
    }
}
module splice() { joint_plate(50, 42, 21, true); }
module joiner() { joint_plate(40, 25, 20, false); }

// ---------------------------------------------------------------- E top plate, F bottom plate
// Same outline as the foam (130 x 70, with 25 mm tabs that plug into the
// notches of panels C / D), 5 mm at the edges and tabs so they sit flush,
// but only a 2.4 mm skin in the middle. Print the flat face down, no
// supports; the rim then points into the hood.
//   E: flat face = OUTSIDE (top). The camera_mount lies flat-face-down in
//      the shallow recess, lens over the 14 mm hole, connector toward the
//      slide end.
//   F: flat face = BOTTOM (on the wedges). The camera_mount stands upside
//      down (walls down) in the recess on the rim side, lens looking up.
// Both: the lens ends up where the card stops (x 67, centre of the channel).
module hood_plate(top) {
    L = 130; W = 70; T = 5; skin = 2.4; rim = 3;
    tabs = [[20, 45], [85, 110]];
    cx = 67; cy = W / 2; cl = 0.3;
    difference() {
        union() {
            difference() {
                cube([L, W, T]);
                translate([rim, rim, skin]) cube([L - 2 * rim, W - 2 * rim, T]);
            }
            for (t = tabs, y = [-T, W]) translate([t[0], y, 0]) cube([t[1] - t[0], T, T]);
        }
        if (top) {
            translate([cx, cy, -1]) cylinder(d = 14, h = T + 2);
            // camera_mount plate outline (35.2 x 19.7), 0.6 deep in the flat face
            translate([cx - 26.6 - cl, cy - 9.85 - cl, -0.01]) cube([35.2 + 2 * cl, 19.7 + 2 * cl, 0.6]);
        } else {
            // camera_mount wall outline (29.2 x 13.7), 0.8 deep in the skin, rim side
            translate([cx - 23.6 - cl, cy - 6.85 - cl, skin - 0.8]) cube([29.2 + 2 * cl, 13.7 + 2 * cl, 2]);
        }
        // notches on the end edges marking the camera line (x 67) and the centre (y 35)
        for (p = [[cx, 0], [cx, W], [0, cy], [L, cy]])
            translate([p[0], p[1], -1]) rotate([0, 0, 45]) cube([2, 2, T + 2], center = true);
    }
}

// ---------------------------------------------------------------- D lower hood panel
// Same as the foam D1 / D2: 130 x 140 x 5, notches in the bottom edge for
// plate F's tabs, straight top edge for the window. 2.4 mm skin with a 5 mm
// rim round the edges and the notches. Print the flat face down; the flat
// face goes OUTSIDE (splices H glue there). D1 and D2 are the same part.
module panel_D() {
    L = 130; H = 140; T = 5; skin = 2.4; rim = 3;
    notches = [[20, 45], [85, 110]];
    difference() {
        union() {
            difference() {
                cube([L, H, T]);
                translate([rim, rim, skin]) cube([L - 2 * rim, H - 2 * rim, T]);
            }
            for (n = notches) translate([n[0] - rim, 0, 0]) cube([n[1] - n[0] + 2 * rim, T + rim, T]);
        }
        for (n = notches) translate([n[0], -1, -1]) cube([n[1] - n[0], T + 1, T + 2]);
        // camera-line notch on the top edge (x 67)
        translate([67, H, -1]) rotate([0, 0, 45]) cube([2, 2, T + 2], center = true);
    }
}

// ---------------------------------------------------------------- W, spaced: clears the motor's ear screws
// The ear screw heads sit inside the wheel's radius, so a wheel pushed all
// the way on rubs them. This one has a 3 mm hub on the back: push it all the
// way on and it stops 3 mm off the motor, clear of the heads, with the
// shaft's flats still well inside the keyed part of the bore. It still sits
// inside the floor slot. Print outer face down (as exported), hub up.
module wheel_spaced(d = 40, spacer = 3) {
    w = 8;
    wheel(d, w);
    translate([0, 0, w]) difference() {
        cylinder(d = 10, h = spacer);
        translate([0, 0, -1]) cylinder(d = SHAFT_D + 2 * fit, h = spacer + 2);
    }
}

// ---------------------------------------------------------------- light versions (less filament, faster)
// Same fit and positions as bracket() and wheel_spaced(); only material that
// carries no load is gone.
module bracket_lite(bz = 28, y0 = 5) {   // bz 25, y0 2: the take-away motor under the slide
    H = 50; t = 2.4; tf = 3; flange_w = 14;
    x0 = 9; x1 = 71;                 // the flange screws are at 15 and 65
    adj = 2; bx = 33;
    module slot2d(d, len) { hull() for (s = [-1, 1]) translate([0, s * len / 2]) circle(d = d); }
    difference() {
        union() {
            translate([x0, y0, 0]) cube([x1 - x0, H - y0, t]);                     // plate
            translate([x0, H - tf, 0]) cube([x1 - x0, tf, flange_w]);              // flange
            for (x = [x0, x1 - 2.4]) translate([x, H - tf, 0])                     // gussets
                rotate([90, 0, 90]) linear_extrude(2.4) polygon([[0, 0], [-10, 0], [0, 8]]);
        }
        translate([0, 0, -1]) linear_extrude(t + 2) {
            translate([bx, bz]) slot2d(BODY_D + 2 * 0.6, 2 * adj);
            translate([bx - WIRE_BOX_W / 2 - 0.5, bz - WIRE_BOX_R - adj - 0.5]) square([WIRE_BOX_W + 1, WIRE_BOX_R + adj]);
            for (dx = [-EAR_PITCH / 2, EAR_PITCH / 2]) translate([bx + dx, bz]) slot2d(EAR_HOLE + 2 * fit, 2 * adj);
        }
        for (x = [15, 65]) translate([x, H + 1, 8.5]) rotate([90, 0, 0]) cylinder(d = 3.8, h = tf + 2);
    }
}

module wheel_lite(d = 40, spacer = 3) {
    w = 8; recess = 1.4; rim = 2.4; hub_r = 5.5;
    difference() {
        wheel(d, w);
        translate([0, 0, -1]) linear_extrude(w + 2) difference() {
            circle(r = d / 2 - recess - rim);
            circle(r = hub_r);
            for (a = [0 : 72 : 359]) rotate(a) translate([0, -1.2]) square([d, 2.4]);
        }
    }
    translate([0, 0, w]) difference() {
        cylinder(d = 10, h = spacer);
        translate([0, 0, -1]) cylinder(d = SHAFT_D + 2 * fit, h = spacer + 2);
    }
}

// ---------------------------------------------------------------- hopper, frame version (least plastic)
// Same inside dimensions, floor, slot, lip, pilot holes and front wall as
// hopper(), but 1.6 mm walls, 45 mm tall (still 100+ cards under the
// weight), and peaked windows in the side and back walls (45 degree tops,
// so nothing sags). The bottom 12 mm of
// the side walls stays solid, where the bottom card's edges slide; the
// front wall stays solid (it holds the stack and carries strip T).
module hopper_frame() {
    wall = 1.6; Hh = 45; band = 12;
    L = 126; CHW = 70; floor_t = 5; gap = 3; back = 5; front = 101;
    x0 = back - wall;
    // windows with a 45-degree peaked top: no flat spans to sag, no supports
    gw = 24; h1 = 11;
    module gable(x, y) { translate([x, y]) polygon([[0, 0], [gw, 0], [gw, h1], [gw / 2, h1 + gw / 2], [0, h1]]); }
    difference() {
        union() {
            translate([x0, 0, 0]) cube([L - x0, CHW, floor_t]);
            for (y = [-wall, CHW]) translate([x0, y, 0]) cube([front + wall - x0, wall, Hh]);
            translate([x0, 0, 0]) cube([wall, CHW, Hh]);
            translate([front, 0, floor_t + gap]) cube([wall, CHW, Hh - floor_t - gap]);
        }
        translate([49, 28, -1]) cube([36, 14, floor_t + 2]);                                   // wheel slot
        for (y = [17, 53]) translate([front - 1, y, 0]) hull()                                  // strip T slots
            for (z = [floor_t + gap + 19 + 1.75, floor_t + gap + 33 - 1.75])
                translate([0, 0, z]) rotate([0, 90, 0]) cylinder(d = 3.5, h = wall + 2, $fn = 24);
        for (x = [35, 85]) translate([x, 50.5, -1]) cylinder(d = 2.5, h = 5, $fn = 24);        // bracket pilot holes
        translate([20, 42 - 0.3, -0.01]) cube([80, 0.6, 0.4]);                                  // bracket line
        // side windows (x along the hopper, z up)
        for (y = [-wall - 1, CHW - 1]) translate([0, y, 0]) rotate([-90, 0, 0]) mirror([0, 1, 0])
            linear_extrude(wall + 2) for (i = [0 : 2]) gable(12 + i * (gw + 3), floor_t + band);
        finger_slots(wall, CHW, floor_t, Hh);
        // back window
        translate([x0 - 1, 0, 0]) rotate([90, 0, 90]) linear_extrude(wall + 2) for (y = [9, 37]) gable(y, floor_t + band);
    }
}

// ---------------------------------------------------------------- take-away rollers on the slide
// The feed wheel only pushes a card until its back edge passes the wheel,
// with the tail still under the stack. A second wheel + motor under the
// slide, 40 mm past the hopper end, with a free roller pressing the card
// onto it, grabs the card's front edge and pulls it all the way out.
//   slide_takeaway: slide() + wheel slot in the floor, axle slots in both
//     walls, band lugs under them, and a guide line for the bracket.
//   takeaway_bracket: bracket_lite with the motor 3 mm lower, because the
//     slide floor is 2 mm (the hopper floor is 5). Glue its flange under
//     the slide floor, flat face on the guide line, flange away from the slot.
//   takeaway_roller + takeaway_axle: the roller rides on the axle, the axle
//     floats in the wall slots; a rubber band on each axle end, looped under
//     the lug below it, pulls the roller down onto the card.
// The second motor goes on a second ULN2003 whose IN1-IN4 are wired to the
// same 4 GPIO pins as the first, so both wheels turn in step.
TA_X = 40;          // take-away wheel / roller, from the slide's hopper end
module slide_takeaway() {
    CHW = 70; wall = 5;
    difference() {
        union() {
            slide();
            for (y = [-wall - 5, CHW + wall]) translate([TA_X - 5, y, 0]) cube([10, 5, 5]);   // band lugs
        }
        translate([TA_X - 12, 27, -1]) cube([24, 15, 5]);                                       // wheel slot
        for (y = [-wall - 1, CHW - 1]) translate([TA_X, y, 0]) rotate([-90, 0, 0])              // axle slots
            linear_extrude(wall + 2) hull() for (z = [6, 18]) translate([0, -z]) circle(d = 4.8, $fn = 24);
        for (y = [-wall - 5 - 1, CHW + wall + 4])                                               // band grooves
            translate([TA_X - 1, y, -1]) cube([2, 2, 7]);
        translate([2, 42 - 0.3, -0.01]) cube([62, 0.6, 0.4]);                                    // bracket line
    }
}
module takeaway_bracket() { bracket_lite(25, 2); }
module takeaway_roller() {                       // prints standing
    difference() { cylinder(d = 16, h = 64); translate([0, 0, -1]) cylinder(d = 5, h = 66); }
}
module takeaway_axle() {                         // prints lying flat; octagon, a flat face down
    len = 92;
    difference() {
        translate([0, 0, 4 / 2 * cos(22.5)]) rotate([0, 90, 0]) rotate([0, 0, 22.5]) cylinder(d = 4, h = len, $fn = 8);
        for (x = [3, len - 4.5]) translate([x, -3, 2.8]) cube([1.5, 6, 3]);                     // band grooves
    }
}

if (part == "wheel") wheel(40);
else if (part == "wheel_big") wheel(42);
else if (part == "wheel_spaced") wheel_spaced(40);
else if (part == "bracket") bracket();
else if (part == "bracket_lite") bracket_lite();
else if (part == "wheel_lite") wheel_lite(40);
else if (part == "throat") throat();
else if (part == "flap") flap();
else if (part == "hopper") hopper();
else if (part == "hopper_light") hopper(2.4);
else if (part == "hopper_frame") hopper_frame();   // thin walls: less plastic, same inside
else if (part == "slide") slide();
else if (part == "slide_takeaway") slide_takeaway();
else if (part == "takeaway_bracket") takeaway_bracket();
else if (part == "takeaway_roller") takeaway_roller();
else if (part == "takeaway_axle") takeaway_axle();
else if (part == "weight") weight();
else if (part == "servo_mount") servo_mount();
else if (part == "camera_mount") camera_mount();
else if (part == "lower_hood") lower_hood();
else if (part == "led_channel") led_channel(120);
else if (part == "led_channel_short") led_channel(60);
else if (part == "plate_E") hood_plate(true);
else if (part == "plate_F") hood_plate(false);
else if (part == "panel_D") panel_D();
else if (part == "splice") splice();
else if (part == "joiner") joiner();
else if (part == "joints") {   // a whole set on one plate: 4 H + 2 J
    for (i = [0 : 3]) translate([(i % 2) * 55, floor(i / 2) * 47, 0]) splice();
    for (i = [0 : 1]) translate([110 + 5, i * 30, 0]) joiner();
}
