// auto-git-backup.mjs — Claude Code Stop hook: master 자동백업 (안전장치 풀장착)
// 설계근거: workflow "autobackup-hook-design" + security-reviewer (2026-06-19)
// 원칙: ① 작업 차단 안 함(exit 0 고정) ② 조용한 실패(.git/autobackup.log)
//   ③ 재진입 가드 ④ 변경 있을 때만 ⑤ 민감파일 2차 필터 ⑥ push 백그라운드
//   ⑦ --force 금지 ⑧ detached/index.lock/대용량 skip
//   ⑨ execFileSync(쉘 미경유)로 명령주입 차단 + timeout
//   ⑩ git add -A 미사용 — 비민감 파일만 개별 add (사용자 수동 staging 보존)
import { execFileSync, spawn } from 'node:child_process';
import { existsSync, readFileSync, writeFileSync } from 'node:fs';

// 1) 재진입 가드 (push 자식에 AUTOBACKUP_RUNNING=1 주입; Stop hook 은 자기 commit 으로
//    재트리거되지 않지만 이중 안전 + cooldown 으로 보강)
if (process.env.AUTOBACKUP_RUNNING === '1') process.exit(0);
const DRYRUN = process.env.AUTOBACKUP_DRYRUN === '1';

let raw = '';
try { for await (const c of process.stdin) raw += c; } catch {}
let cwd = '';
try { cwd = (JSON.parse(raw || '{}').cwd) || ''; } catch {}

const REPO = process.env.CLAUDE_PROJECT_DIR || cwd || process.cwd();
const ts = () => new Date().toISOString();
const log = (m) => { try { writeFileSync(`${REPO}/.git/autobackup.log`, `[${ts()}] ${m}\n`, { flag: 'a' }); } catch {} };

// execFileSync: 쉘을 거치지 않아 파일명/경로의 특수문자로 명령주입 불가. 30초 타임아웃.
const git = (...args) => execFileSync('git', ['-C', REPO, ...args], {
  encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'], timeout: 30000,
}).trim();
const gitSafe = (...args) => { try { return git(...args); } catch { return ''; } };

// .gitignore 누락 대비 2차 민감 필터
const SENSITIVE = new RegExp(
  '(^|/)(' +
  '\\.credentials|\\.env([._-]|$)|\\.envrc|\\.netrc|' +
  '[^/]*\\.pem$|[^/]*\\.key$|' +
  'id_(rsa|dsa|ecdsa|ed25519)([._]|$)|' +
  '\\.npmrc|\\.pypirc|' +
  '\\.aws/|\\.docker/|\\.ssh/|' +
  'credentials\\.json|token\\.json|service.?account.*\\.json|firebase.*\\.json|' +
  'secrets[./]|browser-data/|sessions/|screenshots/|' +
  '[^/]*\\.db(-|$)|margin_sheet' +
  ')', 'i');
// 최상위(루트)의 _ 로 시작하는 임시/분석 파일만 격리 — 하위 __init__.py·_http.py 오탐 방지
const ROOT_TEMP = /^_[^/]*$/;
const COOLDOWN_MS = 120000; // 2분

try {
  if (!existsSync(`${REPO}/.git`)) { log('skip: not a git repo'); process.exit(0); }
  if (existsSync(`${REPO}/.git/index.lock`)) { log('skip: index.lock present'); process.exit(0); }

  let branch;
  try { branch = git('symbolic-ref', '--short', 'HEAD'); } catch { log('skip: detached HEAD'); process.exit(0); }

  const tsFile = `${REPO}/.git/autobackup.last`;
  if (!DRYRUN && existsSync(tsFile)) {
    const last = parseInt(readFileSync(tsFile, 'utf8'), 10) || 0;
    if (Date.now() - last < COOLDOWN_MS) { log('skip: cooldown'); process.exit(0); }
  }

  // 변경 파일 목록 — porcelain prefix 파싱(취약)을 피하고 name-only 로 경로 직접 추출.
  // core.quotepath=false 로 한글 파일명도 그대로. (추적 변경분 + 비-ignore untracked)
  const changed = git('-c', 'core.quotepath=false', 'diff', '--name-only', 'HEAD').split('\n').filter(Boolean);
  const untracked = git('-c', 'core.quotepath=false', 'ls-files', '--others', '--exclude-standard').split('\n').filter(Boolean);
  const files = [...new Set([...changed, ...untracked])];
  if (files.length === 0) { log('skip: no changes'); process.exit(0); }
  const safe = files.filter((f) => !SENSITIVE.test(f) && !ROOT_TEMP.test(f));
  const filtered = files.length - safe.length;
  if (safe.length === 0) { log(`skip: all ${files.length} changes filtered as sensitive`); process.exit(0); }
  if (safe.length > 300) { log(`abort: too many files (${safe.length})`); process.exit(0); }

  if (DRYRUN) {
    log(`DRYRUN ✅ would commit ${safe.length} files on ${branch}; sensitive filtered ${filtered}`);
    process.exit(0);
  }

  // git add -A 미사용: 비민감 파일만 개별 add → 사용자 수동 staging/민감파일 영향 없음
  for (const f of safe) gitSafe('add', '--', f);
  const staged = git('diff', '--cached', '--name-only').split('\n').filter(Boolean);
  if (staged.length === 0) { log('skip: nothing staged'); process.exit(0); }

  git('commit', '-q', '-m', `auto-backup ${ts()}`);
  writeFileSync(tsFile, String(Date.now()));
  log(`committed ${staged.length} files on ${branch} (filtered ${filtered})`);

  // push: 백그라운드 detached, --force 절대 금지. 실패해도 다음 회차 자연 재시도.
  const p = spawn('git', ['-C', REPO, 'push', '--quiet'], {
    detached: true, stdio: 'ignore',
    env: { ...process.env, AUTOBACKUP_RUNNING: '1' },
  });
  p.unref();
  log('push spawned (background)');
} catch (e) {
  log('error: ' + (e?.message?.slice(0, 200) || 'unknown'));
}
process.exit(0);
