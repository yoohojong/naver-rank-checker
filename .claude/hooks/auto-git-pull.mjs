// auto-git-pull.mjs — Claude Code SessionStart hook: 세션 시작 시 원격 최신 반영 (안전장치 풀장착)
// 설계근거: "노트북 작업이 데스크탑에 반영 안 됨" 근본원인 = pull 부재. auto-git-backup(push)과 짝.
// 원칙: ① 작업 차단 안 함(exit 0 고정) ② 조용한 실패 로그(.git/autopull.log)
//   ③ --force/reset 절대 금지 ④ 충돌 시 rebase --abort 로 원상복구(로컬 커밋/작업 무손실)
//   ⑤ --autostash 로 미커밋 변경 보존 후 재적용 ⑥ execFileSync(쉘 미경유)+timeout(명령주입/행 방지)
//   ⑦ 진행중 rebase/merge/detached/index.lock/upstream없음/오프라인 = 안전 skip
import { execFileSync } from 'node:child_process';
import { existsSync, writeFileSync } from 'node:fs';

let raw = '';
try { for await (const c of process.stdin) raw += c; } catch {}
let cwd = '';
try { cwd = (JSON.parse(raw || '{}').cwd) || ''; } catch {}

const REPO = process.env.CLAUDE_PROJECT_DIR || cwd || process.cwd();
const ts = () => new Date().toISOString();
const log = (m) => { try { writeFileSync(`${REPO}/.git/autopull.log`, `[${ts()}] ${m}\n`, { flag: 'a' }); } catch {} };

// execFileSync: 쉘 미경유 → 경로 특수문자로 명령주입 불가. 네트워크 감안 45초 타임아웃.
const git = (...args) => execFileSync('git', ['-C', REPO, ...args], {
  encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'], timeout: 45000,
}).trim();
const gitSafe = (...args) => { try { return git(...args); } catch { return ''; } };

// 이어받기 브리핑: 다른 기기가 한 작업을 세션 시작 화면에 요약(stdout=SessionStart 컨텍스트 주입).
function printResume(branch, commits, changedFiles) {
  try {
    if (!commits.length) return;
    const lines = [`🔄 이어받기 [브랜치: ${branch}] — 다른 곳에서 한 작업 ${commits.length}건 받음:`];
    for (const c of commits.slice(0, 6)) {
      const i = c.indexOf('\t');
      const when = i >= 0 ? c.slice(0, i) : '';
      const subj = i >= 0 ? c.slice(i + 1) : c;
      lines.push(`   • ${subj}${when ? ` (${when})` : ''}`);
    }
    if (commits.length > 6) lines.push(`   … 외 ${commits.length - 6}건`);
    if (changedFiles.length) {
      lines.push(`   바뀐 파일 ${changedFiles.length}개: ${changedFiles.slice(0, 8).join(', ')}${changedFiles.length > 8 ? ' …' : ''}`);
      lines.push('   → 이어가려면 위 파일부터 확인하세요.');
    }
    console.log(lines.join('\n'));
  } catch {}
}

try {
  if (!existsSync(`${REPO}/.git`)) { log('skip: not a git repo'); process.exit(0); }
  if (existsSync(`${REPO}/.git/index.lock`)) { log('skip: index.lock present'); process.exit(0); }
  // 진행중인 rebase/merge 는 절대 건드리지 않음
  if (existsSync(`${REPO}/.git/rebase-merge`) || existsSync(`${REPO}/.git/rebase-apply`) || existsSync(`${REPO}/.git/MERGE_HEAD`)) {
    log('skip: rebase/merge in progress'); process.exit(0);
  }

  let branch;
  try { branch = git('symbolic-ref', '--short', 'HEAD'); } catch { log('skip: detached HEAD'); process.exit(0); }

  // 원격 추적 브랜치(upstream) 없으면 skip
  const upstream = gitSafe('rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{u}');
  if (!upstream) { log(`skip: no upstream for ${branch}`); process.exit(0); }

  // fetch(네트워크). 오프라인이면 조용히 skip.
  try { git('fetch', '--quiet', 'origin'); } catch (e) { log('skip: fetch failed (offline?) ' + (e?.message?.slice(0, 120) || '')); process.exit(0); }

  const behind = parseInt(gitSafe('rev-list', '--count', `HEAD..${upstream}`), 10) || 0;
  const ahead = parseInt(gitSafe('rev-list', '--count', `${upstream}..HEAD`), 10) || 0;
  if (behind === 0) { log(`up-to-date on ${branch} (ahead ${ahead})`); process.exit(0); }

  // 이어받기 브리핑용: pull 전에 '들어올 커밋/바뀔 파일'을 미리 캡처(다른 기기가 한 작업).
  const incoming = gitSafe('log', '--format=%cr%x09%s', `HEAD..${upstream}`).split('\n').filter(Boolean);
  const incomingFiles = gitSafe('-c', 'core.quotepath=false', 'diff', '--name-only', `HEAD..${upstream}`).split('\n').filter(Boolean);

  // pull --rebase --autostash: 미커밋 변경 임시보관→재적용, 로컬 커밋은 원격 위로 재배치. --force 아님.
  try {
    git('pull', '--rebase', '--autostash', '--quiet', 'origin', branch);
    log(`pulled: ${branch} 이(가) behind ${behind}(ahead ${ahead}) → 최신 반영 완료`);
    printResume(branch, incoming, incomingFiles);
  } catch (e) {
    // 진짜 충돌 → 원상복구(rebase --abort 는 pre-rebase 상태로 되돌려 로컬 작업 무손실). 사용자 수동 병합.
    gitSafe('rebase', '--abort');
    log(`CONFLICT: rebase aborted, 원상복구함(behind ${behind}, ahead ${ahead}). 수동 병합 필요. ${e?.message?.slice(0, 120) || ''}`);
    console.log(`⚠️ 이어받기 경고 [${branch}]: 양쪽 기기에서 같은 부분을 편집해 자동 병합 실패 → 원상복구(무손실). 수동 확인 필요.`);
  }
} catch (e) {
  log('error: ' + (e?.message?.slice(0, 200) || 'unknown'));
}
process.exit(0);
