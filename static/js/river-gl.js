/*
 * river-gl.js: a thin WebGL1 helper for the brook. Full-screen fragment programs, textures,
 * render targets. Every texture upload flips Y, so in every shader uv = gl_FragCoord.xy / size
 * and the top row of a canvas or array is the top of the screen.
 */

const UNIFORM_SETTERS = Object.freeze({
  0x1406: (gl, loc, v) => (typeof v === 'number' ? gl.uniform1f(loc, v) : gl.uniform1fv(loc, v)), // FLOAT
  0x8B50: (gl, loc, v) => gl.uniform2fv(loc, v),   // FLOAT_VEC2
  0x8B51: (gl, loc, v) => gl.uniform3fv(loc, v),   // FLOAT_VEC3
  0x8B52: (gl, loc, v) => gl.uniform4fv(loc, v),   // FLOAT_VEC4
  0x1404: (gl, loc, v) => gl.uniform1i(loc, v),    // INT
});

export class GlKit {
  constructor(canvas) {
    const opts = { alpha: false, antialias: false, depth: false, stencil: false,
      premultipliedAlpha: false, preserveDrawingBuffer: false, powerPreference: 'high-performance' };
    const gl = canvas.getContext('webgl', opts) || canvas.getContext('experimental-webgl', opts);
    if (!gl) throw new Error('WebGL is not available');
    this.gl = gl;
    this.buffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, this.buffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
    this.owned = new Set();
  }
  program(fragment) {
    const gl = this.gl;
    const compile = (type, src) => {
      const s = gl.createShader(type);
      gl.shaderSource(s, src);
      gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
        const lines = src.split('\n').map((l, i) => `${i + 1}: ${l}`).join('\n');
        throw new Error(`shader: ${gl.getShaderInfoLog(s)}\n${lines}`);
      }
      return s;
    };
    const p = gl.createProgram();
    gl.attachShader(p, compile(gl.VERTEX_SHADER, 'attribute vec2 aPos; void main() { gl_Position = vec4(aPos, 0.0, 1.0); }'));
    gl.attachShader(p, compile(gl.FRAGMENT_SHADER, fragment));
    gl.bindAttribLocation(p, 0, 'aPos');
    gl.linkProgram(p);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(`link: ${gl.getProgramInfoLog(p)}`);
    const uniforms = new Map();
    const count = gl.getProgramParameter(p, gl.ACTIVE_UNIFORMS);
    for (let i = 0; i < count; i++) {
      const info = gl.getActiveUniform(p, i);
      uniforms.set(info.name.replace(/\[0\]$/, ''), { loc: gl.getUniformLocation(p, info.name), type: info.type });
    }
    return { p, uniforms };
  }
  texture(w, h, { wrap = this.gl.CLAMP_TO_EDGE, filter = this.gl.LINEAR, data = null } = {}) {
    const gl = this.gl, tex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, filter);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, filter);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, wrap);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, wrap);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, w, h, 0, gl.RGBA, gl.UNSIGNED_BYTE, data);
    const t = { tex, w, h, fb: null };
    this.owned.add(t);
    return t;
  }
  /** Replaces a texture's pixels from a typed array or a canvas of the same size. */
  update(t, source, premultiply = false) {
    const gl = this.gl;
    gl.bindTexture(gl.TEXTURE_2D, t.tex);
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, premultiply);
    if (ArrayBuffer.isView(source)) gl.texSubImage2D(gl.TEXTURE_2D, 0, 0, 0, t.w, t.h, gl.RGBA, gl.UNSIGNED_BYTE, source);
    else gl.texSubImage2D(gl.TEXTURE_2D, 0, 0, 0, gl.RGBA, gl.UNSIGNED_BYTE, source);
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
  }
  release(t) {
    if (!t || !this.owned.has(t)) return;
    if (t.fb) this.gl.deleteFramebuffer(t.fb);
    this.gl.deleteTexture(t.tex);
    this.owned.delete(t);
  }
  /** Draws `prog` into texture `target` (or the canvas when target is null). Every active uniform needs a value. */
  draw(prog, values, target, w, h) {
    const gl = this.gl;
    if (target && !target.fb) {
      target.fb = gl.createFramebuffer();
      gl.bindFramebuffer(gl.FRAMEBUFFER, target.fb);
      gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, target.tex, 0);
    }
    gl.bindFramebuffer(gl.FRAMEBUFFER, target ? target.fb : null);
    gl.viewport(0, 0, target ? target.w : w, target ? target.h : h);
    gl.useProgram(prog.p);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.buffer);
    gl.enableVertexAttribArray(0);
    gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
    let unit = 0;
    for (const [name, u] of prog.uniforms) {
      const v = values[name];
      if (v === undefined) throw new Error(`uniform ${name} has no value`);
      if (u.type === gl.SAMPLER_2D) {
        gl.activeTexture(gl.TEXTURE0 + unit);
        gl.bindTexture(gl.TEXTURE_2D, v.tex);
        gl.uniform1i(u.loc, unit);
        unit++;
      } else {
        const set = UNIFORM_SETTERS[u.type];
        if (!set) throw new Error(`uniform ${name}: type ${u.type} is not handled`);
        set(gl, u.loc, v);
      }
    }
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
  }
  dispose() {
    for (const t of [...this.owned]) this.release(t);
    const lose = this.gl.getExtension('WEBGL_lose_context');
    if (lose) lose.loseContext();
  }
}

/* Hashes and value noise shared by the shaders (Dave Hoskins' sine-free hashes). */
export const GLSL_NOISE = `
float hash12(vec2 p) {
  vec3 p3 = fract(vec3(p.xyx) * 0.1031);
  p3 += dot(p3, p3.yzx + 33.33);
  return fract((p3.x + p3.y) * p3.z);
}
vec4 hash42(vec2 p) {
  vec4 p4 = fract(vec4(p.xyxy) * vec4(0.1031, 0.1030, 0.0973, 0.1099));
  p4 += dot(p4, p4.wzxy + 33.33);
  return fract((p4.xxyz + p4.yzzw) * p4.zywx);
}
float vnoise(vec2 p) {
  vec2 i = floor(p), f = fract(p);
  vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(mix(hash12(i), hash12(i + vec2(1.0, 0.0)), u.x),
             mix(hash12(i + vec2(0.0, 1.0)), hash12(i + vec2(1.0, 1.0)), u.x), u.y);
}
float fbm5(vec2 p) {
  float s = 0.0, a = 0.5;
  for (int i = 0; i < 5; i++) { s += a * vnoise(p); p = p * 2.03 + vec2(1.7, 9.2); a *= 0.5; }
  return s / 0.96875;
}
float fbm3(vec2 p) {
  float s = 0.0, a = 0.5;
  for (int i = 0; i < 3; i++) { s += a * vnoise(p); p = p * 2.03 + vec2(1.7, 9.2); a *= 0.5; }
  return s / 0.875;
}
`;
