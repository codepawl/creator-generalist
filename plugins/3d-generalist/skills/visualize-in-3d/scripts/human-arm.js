// What a human arm can do, for any Crucible character with upperarm_/lowerarm_/hand_ bones (Quaternius, UE-style), posed through
// createAssetPose from `crucible/addons/skeleton-pose`. This file imports nothing: vectors are [x, y, z], quaternions [x, y, z, w],
// matrices 16 numbers in column-major order, all in world space.
//
// A hand on a prop used to take its whole rotation from the prop, whatever that did to the wrist: the man held the cartridge with
// the wrist bent 149 degrees and sideways 130. Here a grip says only what the contact fixes (the palm's normal on a flat face, the
// thumb-side axis along an edge) and the hand takes the rest from the forearm, then the result is clamped into the comfortable range.
// Angles come from joint positions and the hand's axes only, so they measure what the viewer sees, not how a bone happens to roll.
//
// The arm is two solver entries for createAssetPose({ ik }), in this order:
//   armReach(side, target, pole)  the built-in two-bone solve: wrist to `target`, elbow toward `pole`, an unreachable target
//                                 leaves the arm straight toward it (ikResults[n].error is the shortfall in metres)
//   armElbowRoll(side, captureArmRest(pose, side))  a custom solver: the elbow folds about the rig's own hinge
//   armHand(side, { palm | edge, fingers })  a custom solver: the grip's hand rotation, clamped into GRIP_COMFORT
// and keepArmInRange(side) as the last entry for an arm posed by a stock clip. carryProp(pose, side, socket) then gives a held
// prop's world matrix from the posed hand.

// Degrees. Anatomical range: standard goniometry reference values (elbow 0-145; forearm pronation 80, supination 85; wrist flexion
// 80, extension 70, radial 20, ulnar 30). Comfort: functional wrist motion is about 40 each way (Palmer 1985, Ryu 1991), and a held
// grip keeps inside that; a push may extend further, which `GRIP_COMFORT` allows.
export const ARM_LIMITS = { elbowFlexion: 145, pronation: 80, supination: 85, wristFlexion: 80, wristExtension: 70, radial: 20, ulnar: 30 }
export const GRIP_COMFORT = { pronation: 70, supination: 75, wristFlexion: 40, wristExtension: 55, radial: 12, ulnar: 22 }
// With the elbow nearly straight the forearm's rotation cannot be told from the shoulder's, so it is neither clamped nor checked.
const ELBOW_BENT_ENOUGH = { from: 10, to: 30 }
// The elbow's hinge is the cross product of the two bones: below about 6 degrees of bend it points anywhere, so the roll fades out
// (these are the cross product's length, near sin of the bend).
const ELBOW_HINGE_DEFINED = { from: 0.05, to: 0.17 }
// The last stop turns a hand back two degrees short of the anatomical range, so rounding never lands on the wrong side of it.
const LAST_STOP = Object.fromEntries(Object.entries(ARM_LIMITS).map(([joint, limit]) => [joint, limit - 2]))
// Without a twist bone, all the forearm's rotation would wring the skin at one joint. The lower arm takes this share and the wrist
// keeps the rest, the way the radius turns along the length of a real forearm.
const FOREARM_ROLL_SHARE = 0.6

const DEGREES = 180 / Math.PI
const NEAR_ZERO = 1e-9
const MAX_LIMIT_PASSES = 12

const subtract = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
const addScaled = (a, b, scale) => [a[0] + b[0] * scale, a[1] + b[1] * scale, a[2] + b[2] * scale]
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
const length = (a) => Math.hypot(a[0], a[1], a[2])
const negate = (a) => [-a[0], -a[1], -a[2]]

function cross(a, b) {
  return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
}

function normalize(a) {
  const size = length(a)
  return size < NEAR_ZERO ? [0, 0, 0] : [a[0] / size, a[1] / size, a[2] / size]
}

// `a` with its part along the unit vector `axis` taken out.
function perpendicularTo(a, axis) {
  return addScaled(a, axis, -dot(a, axis))
}

function smooth(value) {
  const clamped = Math.min(1, Math.max(0, value))
  return clamped * clamped * (3 - 2 * clamped)
}

function multiplyQuaternions(a, b) {
  return [
    a[3] * b[0] + a[0] * b[3] + a[1] * b[2] - a[2] * b[1],
    a[3] * b[1] - a[0] * b[2] + a[1] * b[3] + a[2] * b[0],
    a[3] * b[2] + a[0] * b[1] - a[1] * b[0] + a[2] * b[3],
    a[3] * b[3] - a[0] * b[0] - a[1] * b[1] - a[2] * b[2],
  ]
}

function invertQuaternion(rotation) {
  return [-rotation[0], -rotation[1], -rotation[2], rotation[3]]
}

function rotateVector(rotation, v) {
  const spin = cross(rotation, v)
  const doubled = [spin[0] + rotation[3] * v[0], spin[1] + rotation[3] * v[1], spin[2] + rotation[3] * v[2]]
  return addScaled(v, cross(rotation, doubled), 2)
}

function quaternionFromAxisAngle(axis, angle) {
  const sine = Math.sin(angle / 2)
  return [axis[0] * sine, axis[1] * sine, axis[2] * sine, Math.cos(angle / 2)]
}

// The shortest turn that takes unit vector `from` onto unit vector `to`.
function quaternionFromUnitVectors(from, to) {
  const cosine = dot(from, to)
  if (cosine < -1 + 1e-9) {
    const spare = Math.abs(from[0]) < 0.9 ? [1, 0, 0] : [0, 1, 0]
    return quaternionFromAxisAngle(normalize(cross(from, spare)), Math.PI)
  }
  const axis = cross(from, to)
  const unnormalized = [axis[0], axis[1], axis[2], 1 + cosine]
  const size = Math.hypot(...unnormalized)
  return unnormalized.map((component) => component / size)
}

// The rotation whose local x, y and z axes point along the three given world directions (a right-handed set).
function quaternionFromBasis(xAxis, yAxis, zAxis) {
  const [m00, m10, m20] = xAxis
  const [m01, m11, m21] = yAxis
  const [m02, m12, m22] = zAxis
  const trace = m00 + m11 + m22
  if (trace > 0) {
    const scale = 2 * Math.sqrt(trace + 1)
    return [(m21 - m12) / scale, (m02 - m20) / scale, (m10 - m01) / scale, scale / 4]
  }
  if (m00 > m11 && m00 > m22) {
    const scale = 2 * Math.sqrt(1 + m00 - m11 - m22)
    return [scale / 4, (m01 + m10) / scale, (m02 + m20) / scale, (m21 - m12) / scale]
  }
  if (m11 > m22) {
    const scale = 2 * Math.sqrt(1 + m11 - m00 - m22)
    return [(m01 + m10) / scale, scale / 4, (m12 + m21) / scale, (m02 - m20) / scale]
  }
  const scale = 2 * Math.sqrt(1 + m22 - m00 - m11)
  return [(m02 + m20) / scale, (m12 + m21) / scale, scale / 4, (m10 - m01) / scale]
}

function matrixFromRotationTranslation(rotation, translation) {
  const [x, y, z, w] = rotation
  return [
    1 - 2 * (y * y + z * z), 2 * (x * y + z * w), 2 * (x * z - y * w), 0,
    2 * (x * y - z * w), 1 - 2 * (x * x + z * z), 2 * (y * z + x * w), 0,
    2 * (x * z + y * w), 2 * (y * z - x * w), 1 - 2 * (x * x + y * y), 0,
    translation[0], translation[1], translation[2], 1,
  ]
}

// Hand bone axes, measured from the finger bones of this rig: fingers along local +y, the index side +z on both hands, and the palm
// (where the fingers curl and the thumb sits) local -x on the right hand and +x on the left.
export const palmLocal = (side) => [side === 'r' ? -1 : 1, 0, 0]
const FINGERS_LOCAL = [0, 1, 0]
const INDEX_LOCAL = [0, 0, 1]

// The hand's world rotation for a palm direction and a finger direction (made perpendicular to the palm).
export function handFromPalm(side, palm, fingers) {
  const palmUnit = normalize(palm)
  const fingersUnit = normalize(perpendicularTo(fingers, palmUnit))
  const index = cross(palmUnit, fingersUnit)
  return quaternionFromBasis(side === 'r' ? negate(palmUnit) : palmUnit, fingersUnit, side === 'r' ? negate(index) : index)
}

// The hand's world rotation for an edge it wraps: the index side along `edge`, the fingers (made perpendicular to it) across.
export function handFromEdge(side, edge, fingers) {
  const edgeUnit = normalize(edge)
  const fingersUnit = normalize(perpendicularTo(fingers, edgeUnit))
  const palm = side === 'r' ? cross(edgeUnit, fingersUnit) : cross(fingersUnit, edgeUnit)
  return handFromPalm(side, palm, fingersUnit)
}

// Where a held prop goes when it rides the hand: run it after the arm is posed, every frame, and hand the matrix to the prop's part.
// `socket` is { position, palm | edge, fingers } in the prop's own axes: the grip point and what the contact fixes there. `contactOffset`
// is the grip point in the hand joint's own axes. The grip point lands on the contact, and the hand sits in the prop as the socket says.
export function carryProp(pose, side, socket, contactOffset = [0, 0, 0]) {
  const hand = pose.jointWorld('hand_' + side)
  const handInProp = socket.palm ? handFromPalm(side, socket.palm, socket.fingers) : handFromEdge(side, socket.edge, socket.fingers)
  const propRotation = multiplyQuaternions(hand.rotation, invertQuaternion(handInProp))
  const contact = addScaled(hand.position, rotateVector(hand.rotation, contactOffset), 1)
  const propPosition = subtract(contact, rotateVector(propRotation, socket.position))
  return matrixFromRotationTranslation(propRotation, propPosition)
}

// Shoulder, elbow and wrist of one arm as unit directions: the upper arm and the forearm.
function armDirections(shoulder, elbow, wrist) {
  return { upper: normalize(subtract(elbow, shoulder)), forearm: normalize(subtract(wrist, elbow)) }
}

// The forearm's rotation: 0 is a handshake (palm toward the body's middle), positive turns the palm toward the upper arm's far side
// (pronation, palm down with the elbow at a right angle).
function forearmRotation(side, upper, forearm, palm) {
  const hinge = normalize(cross(upper, forearm))
  const towardMiddle = side === 'r' ? negate(hinge) : hinge
  const palmFlat = normalize(perpendicularTo(palm, forearm))
  const upperFlat = normalize(perpendicularTo(upper, forearm))
  return Math.atan2(dot(palmFlat, upperFlat), dot(palmFlat, towardMiddle))
}

function wristAngles(forearm, palm, fingers, index) {
  const along = dot(forearm, fingers)
  return { flexion: Math.atan2(-dot(forearm, palm), along), radial: Math.atan2(-dot(forearm, index), along) }
}

function elbowFlexionOf(upper, forearm) {
  return Math.acos(Math.min(1, Math.max(-1, dot(upper, forearm)))) * DEGREES
}

// The angles of a hand in degrees, for its world rotation and this upper arm and forearm. `rotation` is null while the elbow is too
// straight to tell the forearm's turn from the shoulder's.
function handAngles(side, upper, forearm, handRotation) {
  const palm = rotateVector(handRotation, palmLocal(side))
  const fingers = rotateVector(handRotation, FINGERS_LOCAL)
  const index = rotateVector(handRotation, INDEX_LOCAL)
  const wrist = wristAngles(forearm, palm, fingers, index)
  const elbowFlexion = elbowFlexionOf(upper, forearm)
  return {
    elbowFlexion,
    rotation: elbowFlexion > ELBOW_BENT_ENOUGH.to ? forearmRotation(side, upper, forearm, palm) * DEGREES : null,
    flexion: wrist.flexion * DEGREES,
    radial: wrist.radial * DEGREES,
  }
}

// The angles of one arm in degrees, from a pose with jointWorld (createAssetPose's result).
export function armAngles(pose, side) {
  const shoulder = pose.jointWorld('upperarm_' + side).position
  const elbow = pose.jointWorld('lowerarm_' + side).position
  const hand = pose.jointWorld('hand_' + side)
  const { upper, forearm } = armDirections(shoulder, elbow, hand.position)
  return handAngles(side, upper, forearm, hand.rotation)
}

// Puts an angle inside its range without a jump. Clamping to the nearer end flips the joint from one end to the other when the wanted
// angle passes through the unreachable side: a 17 cm one-frame hand pop. Here the angle walks back through the range
// while the wanted angle crosses the unreachable arc, so the result is continuous all the way round.
function foldIntoRange(angle, low, high) {
  if (angle >= low && angle <= high) return angle
  const fullTurn = 2 * Math.PI
  const pastHigh = (((angle - high) % fullTurn) + fullTurn) % fullTurn
  return high - ((high - low) * pastHigh) / (fullTurn - (high - low))
}

// One pass: turn the forearm's rotation into range, then the wrist.
function limitHandOnce(hand, side, upper, forearm, limits) {
  let limited = hand
  const palm = rotateVector(limited, palmLocal(side))
  const elbowFlexion = elbowFlexionOf(upper, forearm)
  const rollWeight = smooth((elbowFlexion - ELBOW_BENT_ENOUGH.from) / (ELBOW_BENT_ENOUGH.to - ELBOW_BENT_ENOUGH.from))
  if (rollWeight > 0) {
    const rotation = forearmRotation(side, upper, forearm, palm)
    const allowed = foldIntoRange(rotation, -limits.supination / DEGREES, limits.pronation / DEGREES)
    // A turn about the forearm raises the rotation on the left arm and lowers it on the right: the two palms mirror each other.
    const sign = side === 'r' ? 1 : -1
    const turn = quaternionFromAxisAngle(forearm, sign * (rotation - allowed) * rollWeight)
    limited = multiplyQuaternions(turn, limited)
  }
  const palmNow = rotateVector(limited, palmLocal(side))
  const fingersNow = rotateVector(limited, FINGERS_LOCAL)
  const indexNow = rotateVector(limited, INDEX_LOCAL)
  const wrist = wristAngles(forearm, palmNow, fingersNow, indexNow)
  const flexion = foldIntoRange(wrist.flexion, -limits.wristExtension / DEGREES, limits.wristFlexion / DEGREES)
  const radial = foldIntoRange(wrist.radial, -limits.ulnar / DEGREES, limits.radial / DEGREES)
  // Where the forearm should lie in the hand's own axes, then the smallest turn that puts it there.
  const forearmWanted = normalize(addScaled(addScaled(fingersNow, palmNow, -Math.tan(flexion)), indexNow, -Math.tan(radial)))
  return multiplyQuaternions(quaternionFromUnitVectors(forearmWanted, forearm), limited)
}

function isInsideLimits(angles, limits) {
  const rotationInside = angles.rotation === null || (angles.rotation <= limits.pronation && -angles.rotation <= limits.supination)
  const wristInside = angles.flexion <= limits.wristFlexion && -angles.flexion <= limits.wristExtension
  const radialInside = angles.radial <= limits.radial && -angles.radial <= limits.ulnar
  return rotationInside && wristInside && radialInside
}

// A hand rotation near `hand` whose wrist and forearm stay inside `limits`, for this upper arm and forearm. Turning the wrist back can
// move the forearm's rotation a little, so passes repeat until both hold, the way a far-off grip settles.
export function limitHand(hand, side, upper, forearm, limits = GRIP_COMFORT) {
  let limited = hand
  for (let pass = 0; pass < MAX_LIMIT_PASSES; pass++) {
    limited = limitHandOnce(limited, side, upper, forearm, limits)
    if (isInsideLimits(handAngles(side, upper, forearm, limited), limits)) break
  }
  return limited
}

// The part of the hand's turn about the forearm that the lower arm takes over, with the hand's world rotation and position unchanged.
function shareForearmRoll(context, ids) {
  const { localRotations, update, prepared } = context
  const turnedFromRest = multiplyQuaternions(localRotations[ids.hand], invertQuaternion(prepared.restRotations[ids.hand]))
  const alongForearm = normalize(prepared.restTranslations[ids.hand])
  const twistAmount = dot(turnedFromRest, alongForearm)
  const twistSign = turnedFromRest[3] < 0 ? -1 : 1
  const twistAngle = 2 * Math.atan2(Math.abs(twistAmount), Math.abs(turnedFromRest[3])) * Math.sign(twistAmount) * twistSign
  const share = quaternionFromAxisAngle(alongForearm, twistAngle * FOREARM_ROLL_SHARE)
  localRotations[ids.lower].set(multiplyQuaternions(localRotations[ids.lower], share))
  localRotations[ids.hand].set(multiplyQuaternions(invertQuaternion(share), localRotations[ids.hand]))
  update()
}

// The rig indices of one arm's three joints, from the `resolveJoint` a custom solver's create receives.
function armJointIds(side, resolveJoint, label) {
  return { upper: resolveJoint('upperarm_' + side, label), lower: resolveJoint('lowerarm_' + side, label), hand: resolveJoint('hand_' + side, label) }
}

const valueAt = (value, time) => (typeof value === 'function' ? value(time) : value)

// A custom solver entry for createAssetPose({ ik }): sets the hand of one arm and keeps it inside `limits`, after armReach put the
// wrist in place. Give a grip as `palm` (the palm's normal) or `edge` (the thumb-side axis) with `fingers`, each a vector or a
// function of time; with neither, the hand keeps the rotation the layers gave it and is only clamped. `weight` fades it in.
export function armHand(side, { palm, edge, fingers, limits = GRIP_COMFORT, shareRoll = true, weight = 1 } = {}) {
  return {
    type: 'custom',
    weight,
    create(prepared, resolveJoint, label) {
      const ids = armJointIds(side, resolveJoint, label)
      if (prepared.joints[ids.hand].parent !== ids.lower) throw new RangeError(`${label}: hand_${side} must be the child of lowerarm_${side}.`)
      function solve(time, context, solverWeight) {
        const { state } = context
        const { upper, forearm } = armDirections(state.positions[ids.upper], state.positions[ids.lower], state.positions[ids.hand])
        let wanted = Array.from(state.rotations[ids.hand])
        if (palm) wanted = handFromPalm(side, valueAt(palm, time), valueAt(fingers, time))
        if (edge) wanted = handFromEdge(side, valueAt(edge, time), valueAt(fingers, time))
        context.setWorldRotation(ids.hand, limitHand(wanted, side, upper, forearm, limits), solverWeight)
        if (shareRoll) shareForearmRoll(context, ids)
        return { reached: true, error: 0, warnings: [], limited: [] }
      }
      return { joints: [ids.lower, ids.hand], solve }
    },
  }
}

// The last stop for any posed arm, a stock clip included (the walk clip swings the wrists 26 degrees toward the thumb): turns the
// hand back inside the anatomical range, two degrees short of it. An arm already inside is left exactly as it is.
export function keepArmInRange(side) {
  return armHand(side, { limits: LAST_STOP, shareRoll: false })
}

// The built-in two-bone solve for one arm: the wrist goes to `target` (a point, or a function of time and the wrist's position) and the
// elbow bends toward `pole`. The hand keeps its world rotation, so put an armHand after it.
export function armReach(side, target, pole, options = {}) {
  return { type: 'two-bone', root: 'upperarm_' + side, middle: 'lowerarm_' + side, end: 'hand_' + side, target, pole, ...options }
}

// Which way the arm's bones roll, read from a relaxed clip pose (the rig has no twist bones): the elbow's hinge in the upper arm's and
// the lower arm's own axes. Call it on a pose after `apply`, with the elbow bent, and keep the result for armElbowRoll.
export function captureArmRest(pose, side) {
  const upperBone = pose.jointWorld('upperarm_' + side)
  const lowerBone = pose.jointWorld('lowerarm_' + side)
  const { upper, forearm } = armDirections(upperBone.position, lowerBone.position, pose.jointWorld('hand_' + side).position)
  const hinge = normalize(cross(upper, forearm))
  return {
    upperHinge: rotateVector(invertQuaternion(upperBone.rotation), hinge),
    lowerHinge: rotateVector(invertQuaternion(lowerBone.rotation), hinge),
  }
}

// Turns a joint about the world `axis` so its own `localDirection` lies as close to `wanted` as a turn about that axis can put it.
function rollJointTo(context, joint, axis, localDirection, wanted, weight) {
  const rotation = Array.from(context.state.rotations[joint])
  const currentFlat = perpendicularTo(rotateVector(rotation, localDirection), axis)
  const wantedFlat = perpendicularTo(wanted, axis)
  if (length(currentFlat) < 1e-6 || length(wantedFlat) < 1e-6) return
  const angle = Math.atan2(dot(cross(currentFlat, wantedFlat), axis), dot(currentFlat, wantedFlat))
  context.setWorldRotation(joint, multiplyQuaternions(quaternionFromAxisAngle(axis, angle), rotation), weight)
}

// A custom solver entry for createAssetPose({ ik }), between armReach and armHand: rolls the upper arm and the lower arm about their own
// lengths so the elbow folds about the rig's own hinge (`rest` from captureArmRest), as the skin folds at a real elbow. Crucible's
// two-bone solve turns by the shortest rotations and so lets the roll drift (29 degrees on the test character). The wrist and the
// hand's world rotation stay where armReach put them.
export function armElbowRoll(side, rest, { weight = 1 } = {}) {
  return {
    type: 'custom',
    weight,
    create(prepared, resolveJoint, label) {
      const ids = armJointIds(side, resolveJoint, label)
      function solve(time, context, solverWeight) {
        const { state } = context
        const wristAt = Array.from(state.positions[ids.hand])
        const handRotation = Array.from(state.rotations[ids.hand])
        const { upper, forearm } = armDirections(state.positions[ids.upper], state.positions[ids.lower], wristAt)
        const hingeCross = cross(upper, forearm)
        const hingeDefined = smooth((length(hingeCross) - ELBOW_HINGE_DEFINED.from) / (ELBOW_HINGE_DEFINED.to - ELBOW_HINGE_DEFINED.from))
        const rollWeight = solverWeight * hingeDefined
        if (rollWeight > 0) {
          const hinge = normalize(hingeCross)
          rollJointTo(context, ids.upper, upper, rest.upperHinge, hinge, rollWeight)
          // The lower arm swung round with the upper arm: aim it back at the wrist.
          const swungForearm = normalize(subtract(state.positions[ids.hand], state.positions[ids.lower]))
          const aimBack = quaternionFromUnitVectors(swungForearm, forearm)
          context.setWorldRotation(ids.lower, multiplyQuaternions(aimBack, Array.from(state.rotations[ids.lower])), 1)
          rollJointTo(context, ids.lower, forearm, rest.lowerHinge, hinge, rollWeight)
          context.setWorldRotation(ids.hand, handRotation, 1)
        }
        return { reached: true, error: 0, warnings: [], limited: [] }
      }
      return { joints: [ids.upper, ids.lower, ids.hand], solve }
    },
  }
}

// The film's check: every posed character registers its pose, and the film reads measureWatchedArms() on each frame.
const watchedArms = []
export function watchArms(name, pose, isShown = () => true) {
  watchedArms.push({ name, pose, isShown })
}

function excessOf(angles) {
  return {
    elbowFlexion: angles.elbowFlexion - ARM_LIMITS.elbowFlexion,
    pronation: angles.rotation === null ? -1 : angles.rotation - ARM_LIMITS.pronation,
    supination: angles.rotation === null ? -1 : -angles.rotation - ARM_LIMITS.supination,
    wristFlexion: angles.flexion - ARM_LIMITS.wristFlexion,
    wristExtension: -angles.flexion - ARM_LIMITS.wristExtension,
    radial: angles.radial - ARM_LIMITS.radial,
    ulnar: -angles.radial - ARM_LIMITS.ulnar,
  }
}

export function measureWatchedArms() {
  const faults = []
  const largest = {}
  for (const { name, pose, isShown } of watchedArms) {
    if (!isShown()) continue
    for (const side of ['l', 'r']) {
      for (const [joint, over] of Object.entries(excessOf(armAngles(pose, side)))) {
        const key = `${name} ${side} ${joint}`
        largest[key] = Math.max(largest[key] ?? -Infinity, over)
        if (over > 0) faults.push({ key, over })
      }
    }
  }
  return { faults, largest }
}
