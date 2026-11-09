/**
 * ArrayBuffer → UTF-8 字符串 解码器（小程序环境无 TextDecoder 时兜底）。
 * 带跨 chunk 的多字节序列缓冲（一个中文字符的字节可能被拆在两个 chunk 里）。
 */

function makeTextDecoder() {
  if (typeof TextDecoder !== "undefined") {
    const td = new TextDecoder("utf-8");
    return { decode: function (buf) { return td.decode(buf, { stream: true }); } };
  }
  // 手写 UTF-8 解码
  let pending = []; // 上个 chunk 未完成的多字节前缀
  return {
    decode: function (buf) {
      const bytes = new Uint8Array(buf);
      const all = pending.concat(Array.prototype.slice.call(bytes));
      pending = [];
      let out = "";
      let i = 0;
      while (i < all.length) {
        const b = all[i];
        let cp = 0;
        let len = 0;
        if (b < 0x80) { cp = b; len = 1; }
        else if (b >= 0xc0 && b < 0xe0) { cp = b & 0x1f; len = 2; }
        else if (b >= 0xe0 && b < 0xf0) { cp = b & 0x0f; len = 3; }
        else if (b >= 0xf0 && b < 0xf8) { cp = b & 0x07; len = 4; }
        else { i += 1; continue; } // 非法字节跳过

        if (i + len > all.length) {
          // 尾部不完整：留到下个 chunk
          pending = all.slice(i);
          break;
        }
        let ok = true;
        for (let j = 1; j < len; j++) {
          const c = all[i + j];
          if (c === undefined || (c & 0xc0) !== 0x80) { ok = false; break; }
          cp = (cp << 6) | (c & 0x3f);
        }
        if (!ok) { i += 1; continue; }
        out += String.fromCodePoint(cp);
        i += len;
      }
      return out;
    },
  };
}

let shared = null;
module.exports = {
  decode: function (buf) {
    if (!shared) shared = makeTextDecoder();
    return shared.decode(buf);
  },
  reset: function () { shared = null; },
};
