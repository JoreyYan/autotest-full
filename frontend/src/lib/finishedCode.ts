// 成品码识别(铝壳镭射二维码,v1.7.5 新码直推)
// 9 位 = 年 2 位数字 + 代次 2 个字母 + 流水 4 位数字 + Damm 校验 1 位数字,例如 26HK04426。
// 与 SOAI「明码编号规范」(src/lib/serialCode.ts、backend/ww_order_api.py)
// 以及本仓库后端 parse_finished_code 逐位一致,要改几边一起改。

// 代次可用字母,按此顺序映射为 0-9 参与校验
export const LETTERS = "ACFHKLRTWY";

// Damm 算法准乘表
const DAMM: number[][] = [
  [0, 3, 1, 7, 5, 9, 8, 6, 4, 2],
  [7, 0, 9, 2, 1, 5, 4, 8, 6, 3],
  [4, 2, 0, 6, 8, 7, 1, 3, 5, 9],
  [1, 7, 5, 0, 9, 8, 3, 4, 2, 6],
  [6, 1, 2, 3, 0, 4, 5, 9, 7, 8],
  [3, 6, 7, 4, 2, 0, 9, 5, 8, 1],
  [5, 8, 6, 9, 7, 2, 0, 1, 3, 4],
  [8, 9, 4, 5, 3, 6, 2, 0, 1, 7],
  [9, 4, 3, 8, 6, 1, 7, 2, 0, 5],
  [2, 5, 8, 1, 4, 3, 6, 7, 9, 0],
];

// 二维码内容 https://www.soaipower.com/t/<9位码>;主机(连同协议)不区分大小写
const URL_RE = /^https?:\/\/(www\.)?soaipower\.com\/t\/([0-9A-Za-z]{9})\/?$/i;
const BARE_RE = /^[0-9A-Za-z]{9}$/;
const CODE_RE = /^[0-9]{2}[ACFHKLRTWY]{2}[0-9]{5}$/;

/** 前 8 位算校验位:依次 i = DAMM[i][d],第 3、4 位的 d 是字母在 LETTERS 中的下标。 */
export function checkDigit(payload: string): string {
  let i = 0;
  for (let pos = 0; pos < payload.length; pos++) {
    const ch = payload[pos];
    const d = pos === 2 || pos === 3 ? LETTERS.indexOf(ch) : Number(ch);
    i = DAMM[i][d];
  }
  return String(i);
}

/**
 * 扫到/填入的文字是不是新成品码:是 → 返回大写 9 位码;否则 null。
 * 旧码(260YN0062 这类序号、飞书 27 位 token、飞书 /record/ 链接)一律返回 null。
 */
export function parseFinishedCode(text: unknown): string | null {
  if (typeof text !== "string") return null;
  const s = text.trim();
  let candidate: string;
  const m = s.match(URL_RE);
  if (m) candidate = m[2];
  else if (BARE_RE.test(s)) candidate = s;
  else return null;
  candidate = candidate.toUpperCase();
  if (!CODE_RE.test(candidate)) return null;
  return checkDigit(candidate.slice(0, 8)) === candidate[8] ? candidate : null;
}
