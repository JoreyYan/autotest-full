import { describe, it, expect } from "vitest";
import { LETTERS, checkDigit, parseFinishedCode } from "./finishedCode";

const VALID = "26HK04426";
const DIGITS = "0123456789";
const ALNUM_UPPER = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ";

describe("parseFinishedCode 新成品码", () => {
  it("26HK04426 有效", () => {
    expect(checkDigit("26HK0442")).toBe("6");
    expect(parseFinishedCode(VALID)).toBe(VALID);
  });

  it("与 SOAI ww_order_api.make_code 生成的码一致", () => {
    for (const code of ["26AA00008", "26AC00011", "27YY99998", "25LT12345"]) {
      expect(parseFinishedCode(code)).toBe(code);
    }
  });

  it("代次字母表", () => {
    expect(LETTERS).toBe("ACFHKLRTWY");
  });

  it("任意一位替换成别的字符都无效", () => {
    let checked = 0;
    for (let pos = 0; pos < VALID.length; pos++) {
      for (const ch of ALNUM_UPPER) {
        if (ch === VALID[pos]) continue;
        const bad = VALID.slice(0, pos) + ch + VALID.slice(pos + 1);
        expect(parseFinishedCode(bad), bad).toBeNull();
        checked++;
      }
    }
    expect(checked).toBe(9 * 35);
  });

  it("同一字符类内的单位替换都被校验位抓到(不只是靠正则)", () => {
    for (let pos = 0; pos < VALID.length; pos++) {
      const pool = pos === 2 || pos === 3 ? LETTERS : DIGITS;
      for (const ch of pool) {
        if (ch === VALID[pos]) continue;
        const bad = VALID.slice(0, pos) + ch + VALID.slice(pos + 1);
        expect(parseFinishedCode(bad), bad).toBeNull();
      }
    }
  });

  it("相邻两位对调都无效", () => {
    let checked = 0;
    for (let pos = 0; pos < VALID.length - 1; pos++) {
      if (VALID[pos] === VALID[pos + 1]) continue;
      const bad = VALID.slice(0, pos) + VALID[pos + 1] + VALID[pos] + VALID.slice(pos + 2);
      expect(parseFinishedCode(bad), bad).toBeNull();
      checked++;
    }
    expect(checked).toBeGreaterThan(0);
  });

  it("二维码网址形式", () => {
    expect(parseFinishedCode("https://www.soaipower.com/t/26HK04426")).toBe(VALID);
    expect(parseFinishedCode("https://soaipower.com/t/26HK04426")).toBe(VALID);
    expect(parseFinishedCode("http://www.soaipower.com/t/26HK04426/")).toBe(VALID);
    expect(parseFinishedCode("https://WWW.SoaiPower.COM/t/26HK04426")).toBe(VALID);
    expect(parseFinishedCode("https://www.soaipower.com/t/26hk04426")).toBe(VALID);
    expect(parseFinishedCode("  https://www.soaipower.com/t/26HK04426\r\n")).toBe(VALID);
  });

  it("裸码:去空白、转大写", () => {
    expect(parseFinishedCode(" 26hk04426\n")).toBe(VALID);
  });

  it("网址不对或码不对 → null", () => {
    expect(parseFinishedCode("https://www.soaipower.com/t/26HK04427")).toBeNull();
    expect(parseFinishedCode("https://www.soaipower.com/t/26HK044261")).toBeNull();
    expect(parseFinishedCode("https://www.soaipower.com/t/26HK04426?x=1")).toBeNull();
    expect(parseFinishedCode("https://www.soaipower.com/x/26HK04426")).toBeNull();
    expect(parseFinishedCode("https://m.soaipower.com/t/26HK04426")).toBeNull();
    expect(parseFinishedCode("https://evil.com/t/26HK04426")).toBeNull();
    expect(parseFinishedCode("https://www.soaipower.com.evil.com/t/26HK04426")).toBeNull();
    expect(parseFinishedCode("ftp://www.soaipower.com/t/26HK04426")).toBeNull();
    expect(parseFinishedCode("26HK0442")).toBeNull();
    expect(parseFinishedCode("26HK044260")).toBeNull();
    expect(parseFinishedCode("26HK 04426")).toBeNull();
  });

  it("旧码与飞书标签 → null", () => {
    expect(parseFinishedCode("260YN0062")).toBeNull();
    expect(parseFinishedCode("2602N0186")).toBeNull();
    expect(parseFinishedCode("RIHurixiWeFAwaceOSocl0uenIe")).toBeNull();
    expect(parseFinishedCode("https://smartonep.feishu.cn/record/RIHurixiWeFAwaceOSocl0uenIe")).toBeNull();
    expect(parseFinishedCode("https://smartonep.feishu.cn/record/RIHurixiWeFAwaceOSocl0uenIe?from=scan")).toBeNull();
  });

  it("空值/非字符串 → null", () => {
    expect(parseFinishedCode("")).toBeNull();
    expect(parseFinishedCode("   ")).toBeNull();
    expect(parseFinishedCode(null)).toBeNull();
    expect(parseFinishedCode(undefined)).toBeNull();
    expect(parseFinishedCode(264426)).toBeNull();
    expect(parseFinishedCode({})).toBeNull();
  });
});
