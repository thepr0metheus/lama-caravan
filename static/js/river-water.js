/*
 * river-water.js: the brook's water in WebGL. Three programs:
 *   - normals: a tileable ripple texture, made once;
 *   - bake: the bed, the banks and the rocks, lit by the sun, made once per size;
 *     its alpha holds the water depth;
 *   - compose: every frame, the moving surface over the baked bed: refraction, caustics,
 *     sun flecks, reflections of the canopy, glints and foam.
 */
import { GLSL_NOISE, GlKit } from "./river-gl.js";
import { BROOK } from "./river-world.js";

/** The rock outline in GLSL, written from the same numbers as Rock.radiusAt() in river-world.js. */
class RockGlsl {
  static source() {
    const [a1, a2, a3] = BROOK.rockWobble.map(v => v.toFixed(4));
    return `
uniform vec4 uRock[8];       // xy centre (gl px, y up), z radius (gl px), w height (depth units)
uniform float uRockSeed[8];
uniform int uRockCount;
// The rock outline, the same formula as Rock.radiusAt() in river-world.js. The angle is taken
// with y pointing down, as in JS, hence atan(-d.y, d.x) on GL's y-up pixels.
float rockRadius(vec4 rock, float seed, vec2 d) {
  float a = atan(-d.y, d.x);
  return rock.z * (1.0 + ${a1} * sin(3.0 * a + seed) + ${a2} * sin(5.0 * a + 2.0 * seed) + ${a3} * sin(8.0 * a + 3.3 * seed));
}
`;
  }
}
const BROOK_GLSL_ROCK = RockGlsl.source();

const BROOK_NORMALS_FS = `
precision highp float;
uniform vec2 uRes;
${GLSL_NOISE}
vec2 grad(vec2 cell, vec2 per) {
  cell = mod(cell, per);
  float a = hash12(cell + 0.5) * 6.2831853;
  return vec2(cos(a), sin(a));
}
float pnoise(vec2 p, vec2 per) {
  vec2 i = floor(p), f = fract(p);
  vec2 u = f * f * f * (f * (f * 6.0 - 15.0) + 10.0);
  float a = dot(grad(i, per), f);
  float b = dot(grad(i + vec2(1.0, 0.0), per), f - vec2(1.0, 0.0));
  float c = dot(grad(i + vec2(0.0, 1.0), per), f - vec2(0.0, 1.0));
  float d = dot(grad(i + vec2(1.0, 1.0), per), f - vec2(1.0, 1.0));
  return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}
float height(vec2 uv) {
  float s = 0.0, a = 0.5;
  vec2 per = vec2(3.0, 6.0);   // longer along x: the texture's x runs with the current
  for (int o = 0; o < 4; o++) { s += a * pnoise(uv * per, per); per *= 2.0; a *= 0.5; }
  return s;
}
void main() {
  vec2 uv = gl_FragCoord.xy / uRes;
  float e = 1.0 / uRes.x;
  float h = height(uv);
  float dx = height(uv + vec2(e, 0.0)) - height(uv - vec2(e, 0.0));
  float dy = height(uv + vec2(0.0, e)) - height(uv - vec2(0.0, e));
  vec2 n = -vec2(dx, dy) / (2.0 * e) * 0.03;
  gl_FragColor = vec4(clamp(n * 0.5 + 0.5, 0.0, 1.0), clamp(h * 0.7 + 0.5, 0.0, 1.0), 1.0);
}
`;

const BROOK_BAKE_FS = `
precision highp float;
uniform sampler2D uChan;
uniform vec2 uRes;
uniform float uC;
uniform vec3 uSun;
${GLSL_NOISE}
${BROOK_GLSL_ROCK}

vec3 stoneColor(float h) {
  vec3 c = vec3(0.30, 0.31, 0.32);                       // basalt
  c = mix(c, vec3(0.44, 0.46, 0.48), step(0.20, h));     // blue-grey andesite
  c = mix(c, vec3(0.57, 0.49, 0.37), step(0.40, h));     // ochre sandstone
  c = mix(c, vec3(0.49, 0.36, 0.27), step(0.56, h));     // rust
  c = mix(c, vec3(0.65, 0.63, 0.58), step(0.68, h));     // pale granite
  c = mix(c, vec3(0.38, 0.41, 0.34), step(0.84, h));     // greenish
  c = mix(c, vec3(0.83, 0.81, 0.76), step(0.95, h));     // quartz
  return c;
}

// One layer of pebbles: rounded ovals on a jittered grid. Keeps the highest one at p.
void pebbles(vec2 p, float cell, float fill, float seed,
             inout float best, inout float bestRR, inout vec3 col, inout vec3 nrm, inout float edge) {
  vec2 g = floor(p / cell);
  vec2 f = p / cell - g;
  for (int j = -1; j <= 1; j++) {
    for (int i = -1; i <= 1; i++) {
      vec2 o = vec2(float(i), float(j));
      vec2 id = g + o + vec2(seed * 17.0, seed * 31.0);
      vec4 h = hash42(id);
      if (h.w > fill) continue;
      vec2 c = o + 0.2 + 0.6 * h.xy;
      float ang = h.z * 6.2831853;
      float ca = cos(ang), sa = sin(ang);
      vec2 d = f - c;
      vec2 q = vec2(ca * d.x + sa * d.y, -sa * d.x + ca * d.y);
      float rad = 0.36 + 0.3 * hash12(id * 1.37 + 4.1);
      float asp = 0.55 + 0.42 * hash12(id * 2.11 + 7.3);
      vec2 qs = vec2(q.x / rad, q.y / (rad * asp));
      float a = atan(qs.y, qs.x);
      float wob = 1.0 + 0.06 * sin(a * 2.0 + h.z * 31.0) + 0.035 * sin(a * 5.0 + h.w * 17.0);
      float rr = length(qs) / wob;
      edge = min(edge, rr);
      if (rr >= 1.0) continue;
      float k = max(1.0 - rr * rr, 0.015);
      float hh = pow(k, 0.55) * rad * asp * cell * 0.5;
      if (hh <= best) continue;
      best = hh;
      bestRR = rr;
      vec2 gq = -0.55 * pow(k, -0.45) * vec2(asp * qs.x, qs.y);
      vec2 gd = vec2(ca * gq.x - sa * gq.y, sa * gq.x + ca * gq.y);
      nrm = normalize(vec3(-gd, 1.0));
      vec3 c0 = stoneColor(hash12(id * 3.7 + 1.9));
      c0 *= 0.82 + 0.3 * hash12(id * 5.3 + 2.0);
      c0 *= 0.86 + 0.28 * vnoise(p * 0.7 + id * 7.0);
      float vein = smoothstep(0.05, 0.0, abs(q.x * 0.8 + q.y * 0.6 + (h.x - 0.5) * 0.5)) * step(0.72, h.y);
      col = mix(c0, vec3(0.86, 0.84, 0.78), vein * 0.75);
    }
  }
}

vec3 sandColor(vec2 p) {
  float g = vnoise(p * 0.35) * 0.5 + vnoise(p * 1.3) * 0.3 + hash12(floor(p * 1.2)) * 0.2;
  return mix(vec3(0.40, 0.35, 0.27), vec3(0.62, 0.56, 0.44), g);
}

vec3 bedColor(vec2 p, out float topH) {
  float best = 0.0, bestRR = 1.0, edge = 9.0;
  vec3 col = sandColor(p), nrm = vec3(0.0, 0.0, 1.0);
  pebbles(p, uC * 0.024, 0.85, 1.0, best, bestRR, col, nrm, edge);
  pebbles(p, uC * 0.05, 0.7, 2.0, best, bestRR, col, nrm, edge);
  pebbles(p, uC * 0.095, 0.42, 3.0, best, bestRR, col, nrm, edge);
  float diff = clamp(dot(nrm, uSun), 0.0, 1.0);
  float ao = best > 0.0 ? mix(0.5, 1.0, smoothstep(1.0, 0.5, bestRR)) : mix(0.55, 1.0, smoothstep(1.0, 1.7, edge));
  topH = best;
  return col * (0.42 + 0.78 * diff) * ao;
}

// Fallen leaves: chestnut (long, toothed), beech (oval), alder (round). rgb + coverage.
vec4 litter(vec2 p, float cellK, float density) {
  float cell = uC * cellK;
  vec2 g = floor(p / cell), f = p / cell - g;
  vec4 res = vec4(0.0);
  for (int j = -1; j <= 1; j++) {
    for (int i = -1; i <= 1; i++) {
      vec2 o = vec2(float(i), float(j));
      vec2 id = g + o + 91.0;
      vec4 h = hash42(id);
      if (h.w > density) continue;
      vec2 c = o + 0.15 + 0.7 * h.xy;
      float ang = h.z * 6.2831853;
      vec2 d = f - c;
      vec2 q = vec2(cos(ang) * d.x + sin(ang) * d.y, -sin(ang) * d.x + cos(ang) * d.y);
      float kind = hash12(id * 9.1);
      float len = mix(0.5, 0.85, hash12(id * 3.1));
      float slim = kind < 0.45 ? 0.2 : (kind < 0.8 ? 0.36 : 0.46);
      float u = q.x / len;
      if (abs(u) > 1.0) continue;
      float halfW = slim * len * pow(max(1.0 - u * u, 0.0), 0.7);
      halfW *= 1.0 + (kind < 0.45 ? 0.12 * abs(sin(u * 26.0)) : 0.05 * sin(u * 18.0));
      if (abs(q.y) > halfW) continue;
      float tone = hash12(id * 5.9);
      vec3 lc = mix(vec3(0.52, 0.27, 0.09), vec3(0.80, 0.58, 0.18), tone);
      lc = mix(lc, vec3(0.36, 0.22, 0.12), step(0.78, tone));
      lc = mix(lc, vec3(0.50, 0.50, 0.18), step(0.93, tone));
      float rib = smoothstep(0.03, 0.0, abs(q.y)) * 0.3;
      lc *= 1.0 - rib;
      lc *= 0.8 + 0.3 * (q.y / max(halfW, 1e-3) * 0.5 + 0.5);
      lc *= 0.85 + 0.15 * smoothstep(1.0, 0.7, abs(q.y) / max(halfW, 1e-3));
      res = vec4(lc, 1.0);
    }
  }
  return res;
}

vec3 landColor(vec2 p, float inland) {
  float zone = inland + (fbm5(p / uC * 7.0) - 0.5) * 0.6;
  float topH;
  vec3 gravel = bedColor(p, topH);
  vec3 mud = vec3(0.23, 0.19, 0.14) * (0.8 + 0.4 * vnoise(p * 0.25));
  vec3 shore = mix(mud, gravel * 0.95, step(0.0001, topH) * 0.9);
  vec2 mp = p / uC * 22.0;
  float h0 = fbm5(mp);
  float hx = fbm5(mp + vec2(0.06, 0.0));
  float hy = fbm5(mp + vec2(0.0, 0.06));
  vec3 mn = normalize(vec3((h0 - hx) * 14.0, (h0 - hy) * 14.0, 1.0));
  float fuzz = vnoise(p * 0.55) * 0.55 + vnoise(p * 1.6) * 0.45;
  vec3 moss = mix(vec3(0.13, 0.24, 0.07), vec3(0.38, 0.52, 0.14), smoothstep(0.3, 0.75, h0 * 0.7 + fuzz * 0.45));
  moss = mix(moss, vec3(0.55, 0.56, 0.22), smoothstep(0.8, 0.98, fuzz) * 0.45);
  moss *= 0.5 + 0.65 * clamp(dot(mn, uSun), 0.0, 1.0);
  vec4 leaf = litter(p, 0.055, 0.5);
  moss = mix(moss, leaf.rgb, leaf.a * smoothstep(0.2, 0.5, zone));
  shore = mix(shore, leaf.rgb * 0.85, leaf.a * 0.5 * smoothstep(0.05, 0.25, zone));
  return mix(shore, moss, smoothstep(0.14, 0.34, zone));
}

// The highest rock at p: returns its height in depth units (-1 when none) and its lit colour.
float rockAt(vec2 p, out vec3 col) {
  float top = -1.0;
  col = vec3(0.0);
  for (int i = 0; i < 8; i++) {
    if (i >= uRockCount) break;
    vec4 r = uRock[i];
    vec2 d = p - r.xy;
    float rr = rockRadius(r, uRockSeed[i], d);
    float dist = length(d) / rr;
    if (dist >= 1.0) continue;
    float k = max(1.0 - dist * dist, 0.02);
    float h = pow(k, 0.45) * r.w;
    if (h <= top) continue;
    top = h;
    vec2 grad = -0.72 * pow(k, -0.55) * d / rr;
    vec2 bump = vec2(vnoise(p * 0.09 + 3.0), vnoise(p * 0.09 + 7.0)) - 0.5;
    bump += 0.5 * (vec2(vnoise(p * 0.3 + 1.0), vnoise(p * 0.3 + 5.0)) - 0.5);
    vec3 n = normalize(vec3(-grad + bump * 0.9, 1.0));
    float diff = clamp(dot(n, uSun), 0.0, 1.0);
    vec3 base = mix(vec3(0.24, 0.23, 0.22), vec3(0.43, 0.41, 0.38), fbm3(p * 0.04 + uRockSeed[i]));
    float lichen = smoothstep(0.7, 0.76, vnoise(p * 0.11 + uRockSeed[i] * 3.0)) * 0.7;
    base = mix(base, vec3(0.62, 0.66, 0.54), lichen);
    float mossy = smoothstep(0.45, 0.8, k + (fbm3(p * 0.05 + 9.0) - 0.5) * 0.6) * step(1.0, r.w + 0.2);
    vec3 mossC = mix(vec3(0.16, 0.28, 0.07), vec3(0.40, 0.52, 0.15), vnoise(p * 0.5));
    base = mix(base, mossC, mossy * 0.85);
    col = base * (0.32 + 0.88 * diff);
  }
  return top;
}

void main() {
  vec2 p = gl_FragCoord.xy;
  vec4 ch = texture2D(uChan, p / uRes);
  float code = ch.r + (vnoise(p / uC * 35.0) - 0.5) * 0.045 + (vnoise(p / uC * 120.0) - 0.5) * 0.015;
  float depth = clamp((code - 0.5) * 2.0, 0.0, 1.0);
  float inland = clamp((0.5 - code) * 2.0, 0.0, 1.0);
  vec3 col;
  if (code > 0.5) {
    float topH;
    col = bedColor(p, topH);
    float algae = smoothstep(0.35, 0.75, vnoise(p / uC * 9.0)) * 0.5 + 0.15;
    col = mix(col, col * vec3(0.78, 0.86, 0.55), algae);
    col *= 0.86;
    vec4 leaf = litter(p, 0.07, 0.1);
    col = mix(col, leaf.rgb * 0.7, leaf.a * 0.8);
  } else {
    col = landColor(p, inland);
  }
  float outDepth = depth;
  vec3 rc;
  float rh = rockAt(p, rc);
  if (rh > 0.0) {
    float above = rh - depth;
    if (above > 0.0) {
      outDepth = 0.0;
      col = rc * mix(0.68, 1.0, smoothstep(0.0, 0.12, above));
    } else {
      outDepth = -above;
      col = rc * vec3(0.78, 0.86, 0.6) * 0.8;
    }
  }
  for (int i = 0; i < 8; i++) {
    if (i >= uRockCount) break;
    vec4 r = uRock[i];
    vec2 d = p - r.xy;
    float rr = rockRadius(r, uRockSeed[i], d);
    float dl = length(d);
    if (dl < rr * 0.98) continue;
    float ao = 1.0 - 0.35 * smoothstep(rr * 1.35, rr, dl);
    vec2 sc = r.xy - uSun.xy / uSun.z * r.z * 0.55 * min(r.w, 1.5);
    float sh = smoothstep(r.z * 1.02, r.z * 0.72, length(p - sc));
    col *= ao * (1.0 - 0.45 * sh);
  }
  gl_FragColor = vec4(col, outDepth);
}
`;

const BROOK_COMPOSE_FS = `
precision highp float;
uniform sampler2D uBed;      // rgb lit ground, a water depth (0 dry)
uniform sampler2D uChan;     // g, b current; a broken water
uniform sampler2D uNorm;     // tileable surface normals (rg) and height (b)
uniform sampler2D uRipple;   // ripples: rg slope, b height
uniform sampler2D uUnder;    // fish and other things under the surface (premultiplied)
uniform sampler2D uShade;    // shadows on the bed (a)
uniform sampler2D uSunMap;   // canopy field (r); smoothstep(uSunEdge) gives the sun flecks
uniform vec2 uRes;
uniform float uC;
uniform float uTime;
uniform float uFlowMax;
uniform float uDepthPx;
uniform vec2 uAxis;
uniform vec2 uSunEdge;
uniform vec3 uSun;
${GLSL_NOISE}
${BROOK_GLSL_ROCK}

float caustic(vec2 p) {
  // the well-known tileable water caustic (joltz0r, Dave Hoskins), four iterations
  vec2 i = p;
  float c = 1.0;
  for (int n = 0; n < 4; n++) {
    float t = uTime * 0.38 * (1.0 - 3.5 / float(n + 1));
    i = p + vec2(cos(t - i.x) + sin(t + i.y), sin(t - i.y) + cos(t + i.x));
    c += 1.0 / length(vec2(p.x / (sin(i.x + t) / 0.005), p.y / (cos(i.y + t) / 0.005)));
  }
  c /= 4.0;
  c = 1.17 - pow(c, 1.4);
  return pow(abs(c), 7.0);
}

void main() {
  vec2 p = gl_FragCoord.xy;
  vec2 uv = p / uRes;
  vec4 bed = texture2D(uBed, uv);
  float depth = bed.a;
  float flutter = (vnoise(p / uC * 11.0 + vec2(uTime * 0.31, -uTime * 0.23)) - 0.5) * 0.035;
  float sun = smoothstep(uSunEdge.x, uSunEdge.y, texture2D(uSunMap, uv).r + flutter);
  vec2 perp = vec2(-uAxis.y, uAxis.x);

  float shadeDry = texture2D(uShade, uv).a;
  vec3 dry = bed.rgb * mix(0.55, 1.15, sun) * (1.0 - shadeDry * mix(0.25, 0.6, sun));

  vec4 ch = texture2D(uChan, uv);
  vec2 flow = (ch.gb * 2.0 - 1.0) * uFlowMax;
  float speed = length(flow) / (uFlowMax / 1.8);
  float turb = ch.a;

  // flow-mapped surface: two phases of one pattern, each reset while the other is in view
  vec2 sp = vec2(dot(p, uAxis), dot(p, perp)) / uC;
  vec2 sf = vec2(dot(flow, uAxis), dot(flow, perp)) / uC;
  float cyc = 2.4;
  float ph0 = fract(uTime / cyc), ph1 = fract(uTime / cyc + 0.5);
  float w = abs(ph0 * 2.0 - 1.0);
  vec2 a0 = (sp - sf * ph0 * cyc) * vec2(4.0, 7.0);
  vec2 a1 = (sp - sf * ph1 * cyc) * vec2(4.0, 7.0) + vec2(0.31, 0.57);
  vec4 t0 = texture2D(uNorm, a0), t1 = texture2D(uNorm, a1);
  vec2 n = mix(t0.rg, t1.rg, w) * 2.0 - 1.0;
  vec2 b0 = (sp - sf * ph0 * cyc) * vec2(11.0, 17.0) + 0.5;
  vec2 b1 = (sp - sf * ph1 * cyc) * vec2(11.0, 17.0) + vec2(0.73, 0.19);
  n += 0.55 * (mix(texture2D(uNorm, b0).rg, texture2D(uNorm, b1).rg, w) * 2.0 - 1.0);
  float rough = 0.08 + 0.5 * clamp(speed, 0.0, 1.2) + 0.7 * turb;
  vec2 ns = (n.x * uAxis + n.y * perp) * rough;
  ns += (texture2D(uRipple, uv).rg * 2.0 - 1.0) * 1.3;
  vec3 N = normalize(vec3(ns, 1.0));

  // the bed, the fish and the shadows, all seen through the moving surface
  vec2 off = -N.xy * depth * uDepthPx / uRes;
  vec3 floorC = texture2D(uBed, uv + off).rgb;
  float sh = texture2D(uShade, uv + off).a;
  float lightOpen = mix(0.56, 1.16, sun);
  float light = lightOpen * (1.0 - sh * mix(0.42, 0.72, sun));
  vec3 col = floorC * light;
  vec2 cp = sp * 9.0 - vec2(uTime * 0.35, 0.0) - 250.0 + N.xy * 0.6;
  float c = caustic(cp);
  col += vec3(1.0, 0.95, 0.80) * c * 0.6 * sun * (1.0 - sh) * smoothstep(0.03, 0.22, depth) * (1.0 - 0.35 * depth);

  // water drinks the red first: deeper water turns green-blue; a mountain stream stays clear
  vec3 absorb = exp(-depth * vec3(1.05, 0.5, 0.42));
  vec3 deepC = vec3(0.06, 0.17, 0.16) * mix(0.6, 1.15, sun);
  col = col * absorb + deepC * (1.0 - absorb);

  // the fish swim above the bed, so less water stands between them and the eye
  vec4 under = texture2D(uUnder, uv + off * 0.55);
  vec3 absorbFish = exp(-depth * 0.35 * vec3(1.05, 0.5, 0.42));
  vec3 fishC = under.rgb * (lightOpen + c * 0.35 * sun) * absorbFish + deepC * under.a * (1.0 - absorbFish);
  col = col * (1.0 - under.a) + fishC;

  // canopy and sky in the surface: the gaps above are where the flecks come from
  vec3 R = reflect(vec3(0.0, 0.0, -1.0), N);
  float holes = smoothstep(uSunEdge.x + 0.02, uSunEdge.y + 0.06, texture2D(uSunMap, uv + R.xy * uC * 1.3 / uRes).r);
  vec3 env = mix(vec3(0.03, 0.07, 0.05), vec3(0.72, 0.82, 0.84), holes);
  float fres = 0.03 + 0.6 * pow(1.0 - N.z, 2.5);
  col = mix(col, env, fres);
  // glints: an artist's sun a little nearer the zenith, so ripples catch it as they would from a slant
  vec3 glintSun = normalize(vec3(uSun.xy * 0.42, 1.0));
  float spec = pow(max(dot(R, glintSun), 0.0), 700.0);
  col += vec3(1.0, 0.97, 0.88) * spec * 2.6 * smoothstep(0.25, 0.8, sun) * smoothstep(0.01, 0.08, depth);

  // foam: bubbly specks behind the rocks and in the riffles, a broken collar on the rocks' noses
  float fn = mix(t0.b, t1.b, w);
  float specks = smoothstep(0.6, 0.78, fn + (vnoise(p * 0.22 + sf * uTime * 40.0) - 0.5) * 0.25);
  float foam = specks * turb * turb * 0.75;
  for (int i = 0; i < 8; i++) {
    if (i >= uRockCount) break;
    vec4 r = uRock[i];
    vec2 d = p - r.xy;
    float rr = rockRadius(r, uRockSeed[i], d);
    float dl = length(d);
    float ring = smoothstep(rr * 1.16, rr * 1.01, dl) * smoothstep(rr * 0.93, rr * 1.0, dl);
    float nose = smoothstep(0.2, -0.7, dot(d / max(dl, 1.0), normalize(flow + vec2(1e-4, 0.0))));
    float broken = smoothstep(0.35, 0.75, vnoise(p * 0.18 + vec2(uTime * 1.3, -uTime * 0.9)));
    foam = max(foam, ring * (0.12 + 0.7 * nose) * broken * step(1.0, r.w + 0.25));
  }
  col = mix(col, vec3(0.88, 0.93, 0.91) * mix(0.62, 1.08, sun), clamp(foam, 0.0, 1.0) * step(0.001, depth));

  // the shore: a thin film of water, then a bright meniscus line
  col = mix(dry, col, smoothstep(0.0, 0.04, depth));
  col += 0.05 * (smoothstep(0.0, 0.012, depth) - smoothstep(0.012, 0.035, depth));

  vec2 vq = (uv - 0.5) * vec2(uRes.x / uRes.y, 1.0);
  col *= 1.0 - 0.26 * pow(length(vq) / 0.9, 2.4);
  gl_FragColor = vec4(col, 1.0);
}
`;

/** Owns the GL programs and textures of the brook; rebuilt on resize, drawn every frame. */
export class BrookWater {
  constructor(canvas) {
    this.kit = new GlKit(canvas);
    const gl = this.kit.gl;
    this.bakeProg = this.kit.program(BROOK_BAKE_FS);
    this.composeProg = this.kit.program(BROOK_COMPOSE_FS);
    const normals = this.kit.program(BROOK_NORMALS_FS);
    this.normalTex = this.kit.texture(256, 256, { wrap: gl.REPEAT });
    this.kit.draw(normals, { uRes: [256, 256] }, this.normalTex);
    this.sized = [];
  }
  /** (Re)builds the size-dependent textures and bakes the ground. All lengths in CSS px × scale. */
  resize(glW, glH, scale, world) {
    const kit = this.kit;
    for (const t of this.sized) kit.release(t);
    const { channel, ripples, under, shade, canopy } = world;
    this.w = glW; this.h = glH; this.scale = scale;
    this.chanTex = kit.texture(channel.gw, channel.gh, { data: channel.bytes });
    this.bedTex = kit.texture(glW, glH);
    this.rippleTex = kit.texture(ripples.cols, ripples.rows);
    this.underTex = kit.texture(under.width, under.height);
    this.shadeTex = kit.texture(shade.width, shade.height);
    this.sunTex = kit.texture(canopy.cols, canopy.rows, { data: canopy.bytes });
    this.sized = [this.chanTex, this.bedTex, this.rippleTex, this.underTex, this.shadeTex, this.sunTex];
    const rocks = new Float32Array(32), seeds = new Float32Array(8);
    channel.rocks.forEach((r, i) => {
      rocks.set([r.x * scale, glH - r.y * scale, r.r * scale, r.height], i * 4);
      seeds[i] = r.seed;
    });
    this.common = {
      uRes: [glW, glH], uC: channel.C * scale,
      uRock: rocks, uRockSeed: seeds, uRockCount: channel.rocks.length,
      uSun: [BROOK.sun.x, -BROOK.sun.y, BROOK.sun.z],
    };
    kit.draw(this.bakeProg, { ...this.common, uChan: this.chanTex }, this.bedTex);
  }
  draw(t, world) {
    const kit = this.kit, { channel, ripples, under, shade, canopy } = world;
    kit.update(this.rippleTex, ripples.pack());
    kit.update(this.underTex, under.canvas, true);
    kit.update(this.shadeTex, shade.canvas);
    if (canopy.dirty) { kit.update(this.sunTex, canopy.bytes); canopy.dirty = false; }
    kit.draw(this.composeProg, {
      ...this.common,
      uBed: this.bedTex, uChan: this.chanTex, uNorm: this.normalTex, uRipple: this.rippleTex,
      uUnder: this.underTex, uShade: this.shadeTex, uSunMap: this.sunTex,
      uTime: t, uFlowMax: channel.vmax * 1.8 * this.scale, uDepthPx: channel.C * BROOK.refractDepth * this.scale,
      uAxis: [channel.axis.x, -channel.axis.y], uSunEdge: BROOK.sunEdge,
    }, null, this.w, this.h);
  }
  dispose() { this.kit.dispose(); }
}
