let nicknameAvailable = false;
// 무기/리그 선택 상태
const filterState = {
    player: { weapon: '', league: '' },
    child: { weapon: '', league: '' },
};

document.addEventListener('DOMContentLoaded', function() {
    // 닉네임 실시간 확인
    const nicknameInput = document.getElementById('nickname');
    const nicknameStatus = document.getElementById('nicknameStatus');
    let nicknameTimer = null;

    nicknameInput.addEventListener('input', function() {
        this.value = this.value.replace(/[^a-zA-Z0-9_]/g, '');
        clearTimeout(nicknameTimer);
        const val = this.value;

        if (val.length < 3) {
            nicknameStatus.textContent = val.length > 0 ? '3자 이상' : '';
            nicknameStatus.className = 'nickname-status taken';
            nicknameAvailable = false;
            updateSubmitState();
            return;
        }

        nicknameStatus.textContent = '확인 중...';
        nicknameStatus.className = 'nickname-status checking';

        nicknameTimer = setTimeout(async () => {
            try {
                const res = await fetch('/auth/check-nickname?nickname=' + encodeURIComponent(val));
                const data = await res.json();
                if (nicknameInput.value === val) {
                    if (data.available) {
                        nicknameStatus.textContent = '사용 가능';
                        nicknameStatus.className = 'nickname-status available';
                        nicknameAvailable = true;
                    } else {
                        nicknameStatus.textContent = data.reason || '사용 불가';
                        nicknameStatus.className = 'nickname-status taken';
                        nicknameAvailable = false;
                    }
                }
            } catch (e) {
                nicknameStatus.textContent = '';
                nicknameAvailable = false;
            }
            updateSubmitState();
        }, 400);
    });

    // 회원 유형 변경 → 조건부 섹션 토글
    document.querySelectorAll('.type-card input[name="member_type"]').forEach(radio => {
        radio.addEventListener('change', onMemberTypeChange);
    });
    document.querySelectorAll('input[name="coach_role"]').forEach(radio => {
        radio.addEventListener('change', updateSubmitState);
    });

    // 무기/리그 세그먼트 버튼
    document.querySelectorAll('.segmented .seg-btn').forEach(btn => {
        btn.addEventListener('click', function() {
            const group = this.parentElement;
            const target = group.dataset.target;
            const isLeague = group.classList.contains('segmented-league');
            const key = isLeague ? 'league' : 'weapon';
            const val = isLeague ? this.dataset.league : this.dataset.weapon;

            // 토글 (같은 값 재클릭 시 해제)
            if (this.classList.contains('active')) {
                this.classList.remove('active');
                filterState[target][key] = '';
            } else {
                group.querySelectorAll('.seg-btn').forEach(b => b.classList.remove('active'));
                this.classList.add('active');
                filterState[target][key] = val;
            }
        });
    });

    // 필수 동의
    document.querySelectorAll('.consent-required').forEach(cb => {
        cb.addEventListener('change', updateSubmitState);
    });

    onMemberTypeChange();
});


function getSelectedMemberType() {
    const checked = document.querySelector('input[name="member_type"]:checked');
    const val = checked ? checked.value : 'general';
    if (val === 'coach_group') {
        const role = document.querySelector('input[name="coach_role"]:checked');
        return role ? role.value : 'club_coach';
    }
    return val;
}

function onMemberTypeChange() {
    const checked = document.querySelector('input[name="member_type"]:checked');
    const cardType = checked ? checked.value : 'general';

    document.getElementById('coachSubType').style.display = (cardType === 'coach_group') ? 'block' : 'none';
    document.getElementById('playerConnectSection').style.display = (cardType === 'player') ? 'block' : 'none';
    document.getElementById('childConnectSection').style.display = (cardType === 'player_parent') ? 'block' : 'none';
    document.getElementById('orgConnectSection').style.display = (cardType === 'coach_group') ? 'block' : 'none';

    // 유형 전환 시 다른 유형의 선택값 초기화 (엉뚱한 claim 방지)
    if (cardType !== 'player') deselectPlayer();
    if (cardType !== 'player_parent') deselectChild();
    if (cardType !== 'coach_group') deselectOrg();

    // 선수회원이면 이름 자동 채움
    if (cardType === 'player') {
        const fn = document.getElementById('full_name').value.trim();
        if (fn && !document.getElementById('playerSearchName').value) {
            document.getElementById('playerSearchName').value = fn;
        }
    }
    updateSubmitState();
}

// 리그 기준 게이팅: 우리 DB에서 중등부 이하로만 확인되는 선수는 본인 가입 불가
// (고등부/대학부/일반부 기록이 하나라도 있으면 성인 리그로 보고 허용)
const ADULT_LEAGUES = ['high', 'university', 'senior'];
function isMinorLeaguePlayer(leagues) {
    if (!leagues || leagues.length === 0) return false; // 리그 정보 없음 → 판단 불가, 막지 않음
    return !leagues.some(l => ADULT_LEAGUES.includes(l));
}

function updateSubmitState() {
    const required = document.querySelectorAll('.consent-required');
    const allChecked = Array.from(required).every(cb => cb.checked);
    document.getElementById('submitBtn').disabled = !(allChecked && nicknameAvailable);
}


// 폼 제출 전: 코치 그룹이면 실제 member_type을 세부 역할로 치환
document.getElementById('registerForm').addEventListener('submit', function(e) {
    if (!nicknameAvailable) {
        e.preventDefault();
        alert('사용 가능한 닉네임을 입력해주세요.');
        return;
    }
    const email = document.getElementById('email').value;
    if (!email || email.toLowerCase() === 'none') {
        e.preventDefault();
        alert('이메일을 입력해주세요.');
        return;
    }
    const required = document.querySelectorAll('.consent-required');
    if (!Array.from(required).every(cb => cb.checked)) {
        e.preventDefault();
        alert('필수 동의 항목을 체크해주세요.');
        return;
    }

    // coach_group → 세부 역할 값으로 교체하여 전송
    const checked = document.querySelector('input[name="member_type"]:checked');
    if (checked && checked.value === 'coach_group') {
        const role = document.querySelector('input[name="coach_role"]:checked');
        checked.value = role ? role.value : 'club_coach';
    }
});


// =============================================
// Search AJAX
// =============================================
function _esc(s) {
    if (!s) return '';
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML.replace(/'/g, '&#39;').replace(/"/g, '&quot;');
}

const WEAPON_LABELS = { epee: '에페', foil: '플뢰레', sabre: '사브르' };
const LEAGUE_LABELS = { elementary: '초등부', middle: '중등부', high: '고등부', university: '대학부', senior: '일반부' };

function _renderPlayerResults(data, containerId, selectFn, gateMinor) {
    const container = document.getElementById(containerId);
    if (!data.results || data.results.length === 0) {
        container.innerHTML = '<div class="no-results">검색 결과가 없습니다. 가입 후 인증 페이지에서 연결할 수 있습니다.</div>';
        return;
    }
    container.innerHTML = data.results.map(p => {
        const pName = p.player_name || p.name || '';
        const detail = [
            p.team_name || '',
            p.birth_decade || '',
        ].filter(Boolean).join(' · ');
        const badges = []
            .concat((p.weapons || []).map(w => WEAPON_LABELS[w] || w))
            .concat((p.leagues || []).map(l => LEAGUE_LABELS[l] || l));
        const badgeHtml = badges.length
            ? '<div class="result-badges">' + badges.map(b => '<span class="result-badge">' + _esc(b) + '</span>').join('') + '</div>'
            : '';

        // 선수회원 흐름에서 중등부 이하 선수는 선택 차단 → 보호자 계정 안내
        const blocked = gateMinor && isMinorLeaguePlayer(p.leagues);
        const action = blocked
            ? '<span class="result-blocked">보호자 계정 필요</span>'
            : '<button type="button" class="result-select-btn" onclick="' + selectFn + '(' + p.id + ', \'' + _esc(pName) + '\', \'' + _esc(p.team_name || '') + '\', \'' + _esc(p.birth_decade || '') + '\')">선택</button>';

        return '<div class="search-result-item' + (blocked ? ' result-item-blocked' : '') + '">' +
            '<div class="result-info">' +
                '<span class="result-name">' + _esc(pName) + '</span>' +
                '<div class="result-detail">' + _esc(detail) + '</div>' +
                badgeHtml +
            '</div>' +
            action +
        '</div>';
    }).join('');
}

async function searchPlayers() {
    const name = document.getElementById('playerSearchName').value.trim();
    if (name.length < 2) { alert('이름을 2자 이상 입력하세요.'); return; }
    const params = new URLSearchParams({ name });
    if (filterState.player.weapon) params.set('weapon', filterState.player.weapon);
    if (filterState.player.league) params.set('league', filterState.player.league);
    try {
        const res = await fetch('/auth/public/player-search?' + params);
        const data = await res.json();
        _renderPlayerResults(data, 'playerSearchResults', 'selectPlayer', true);
    } catch (e) { alert('검색 중 오류가 발생했습니다.'); }
}

function selectPlayer(id, name, team, birthLabel) {
    document.getElementById('selectedPlayerId').value = id;
    document.getElementById('playerSelected').style.display = 'flex';
    const detail = [name, team, birthLabel || ''].filter(Boolean).join(' · ');
    document.getElementById('playerSelectedInfo').textContent = detail;
    document.getElementById('playerSearchResults').innerHTML = '';
}

function deselectPlayer() {
    document.getElementById('selectedPlayerId').value = '';
    document.getElementById('playerSelected').style.display = 'none';
}

async function searchChildren() {
    const name = document.getElementById('childSearchName').value.trim();
    if (name.length < 2) { alert('이름을 2자 이상 입력하세요.'); return; }
    const params = new URLSearchParams({ name });
    const team = document.getElementById('childSearchTeam').value.trim();
    if (team) params.set('team', team);
    if (filterState.child.weapon) params.set('weapon', filterState.child.weapon);
    if (filterState.child.league) params.set('league', filterState.child.league);
    try {
        const res = await fetch('/auth/public/child-search?' + params);
        const data = await res.json();
        _renderPlayerResults(data, 'childSearchResults', 'selectChild', false);
    } catch (e) { alert('검색 중 오류가 발생했습니다.'); }
}

function selectChild(id, name, team, birthLabel) {
    document.getElementById('selectedChildPlayerId').value = id;
    document.getElementById('selectedChildName').value = name;
    // 정밀 생년은 더 이상 공개검색 응답에 포함되지 않음(EVAL P1-2).
    // 서버가 matched_player_id로 관리자 검토 시 대조하므로 클라이언트는 연도를 보관하지 않는다.
    document.getElementById('selectedChildBirthYear').value = '';
    document.getElementById('selectedChildTeam').value = team;
    document.getElementById('childSelected').style.display = 'flex';
    const detail = [name, team, birthLabel || ''].filter(Boolean).join(' · ');
    document.getElementById('childSelectedInfo').textContent = detail;
    document.getElementById('childSearchResults').innerHTML = '';
}

function deselectChild() {
    document.getElementById('selectedChildPlayerId').value = '';
    document.getElementById('selectedChildName').value = '';
    document.getElementById('selectedChildBirthYear').value = '';
    document.getElementById('selectedChildTeam').value = '';
    document.getElementById('childSelected').style.display = 'none';
}

async function searchOrgs() {
    const name = document.getElementById('orgSearchName').value.trim();
    if (name.length < 2) { alert('조직명을 2자 이상 입력하세요.'); return; }
    try {
        const res = await fetch('/auth/public/org-search?name=' + encodeURIComponent(name));
        const data = await res.json();
        const container = document.getElementById('orgSearchResults');
        if (!data.results || data.results.length === 0) {
            container.innerHTML = '<div class="no-results">검색 결과가 없습니다.</div>';
            return;
        }
        const orgTypeLabels = { club: '클럽', middle_school: '중학교', high_school: '고등학교', university: '대학교', business: '실업팀' };
        container.innerHTML = data.results.map(o => {
            const typeLabel = orgTypeLabels[o.org_type] || o.org_type || '';
            const region = [o.province || '', o.city || ''].filter(Boolean).join(' ');
            const detail = [typeLabel, region].filter(Boolean).join(' · ');
            return '<div class="search-result-item">' +
                '<div class="result-info">' +
                    '<span class="result-name">' + _esc(o.name) + '</span>' +
                    '<div class="result-detail">' + _esc(detail) + '</div>' +
                '</div>' +
                '<button type="button" class="result-select-btn" onclick="selectOrg(' + o.id + ', \'' + _esc(o.name) + '\', \'' + _esc(typeLabel) + '\')">선택</button>' +
            '</div>';
        }).join('');
    } catch (e) { alert('검색 중 오류가 발생했습니다.'); }
}

function selectOrg(id, name, typeLabel) {
    document.getElementById('selectedOrgId').value = id;
    document.getElementById('orgSelected').style.display = 'flex';
    const detail = [name, typeLabel].filter(Boolean).join(' · ');
    document.getElementById('orgSelectedInfo').textContent = detail;
    document.getElementById('orgSearchResults').innerHTML = '';
}

function deselectOrg() {
    document.getElementById('selectedOrgId').value = '';
    document.getElementById('orgSelected').style.display = 'none';
}
