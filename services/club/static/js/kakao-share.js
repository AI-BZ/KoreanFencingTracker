/**
 * Kakao Share Utility for FencingMind Club
 * 코치/감독이 개인 카카오톡으로 메시지를 공유할 수 있는 기능
 */

const KakaoShare = {
    _initialized: false,
    _appKey: null,

    /**
     * Kakao SDK 초기화
     * @param {string} appKey - Kakao JavaScript App Key
     */
    init(appKey) {
        if (!appKey) {
            console.warn('Kakao App Key가 설정되지 않았습니다.');
            return false;
        }
        if (typeof Kakao === 'undefined') {
            console.warn('Kakao SDK가 로드되지 않았습니다.');
            return false;
        }
        if (!Kakao.isInitialized()) {
            Kakao.init(appKey);
        }
        this._initialized = Kakao.isInitialized();
        this._appKey = appKey;
        if (this._initialized) {
            console.log('Kakao SDK initialized');
        }
        return this._initialized;
    },

    /**
     * 초기화 상태 확인
     */
    isReady() {
        return this._initialized && typeof Kakao !== 'undefined' && Kakao.isInitialized();
    },

    /**
     * 공지사항/메시지 카카오톡 공유
     * @param {Object} params
     * @param {string} params.title - 제목
     * @param {string} params.content - 내용 (최대 200자)
     * @param {string} [params.linkUrl] - 클릭 시 이동 URL
     * @param {string} [params.buttonText] - 버튼 텍스트
     */
    shareMessage({ title, content, linkUrl, buttonText = '자세히 보기' }) {
        if (!this.isReady()) {
            alert('카카오톡 공유 기능을 사용할 수 없습니다.\nKAKAO_CLIENT_ID 설정을 확인해주세요.');
            return;
        }

        const baseUrl = window.location.origin;
        const url = linkUrl || baseUrl + '/api/club/';

        Kakao.Share.sendDefault({
            objectType: 'feed',
            content: {
                title: title,
                description: (content || '').substring(0, 200),
                imageUrl: baseUrl + '/static/icons/icon-512x512.png',
                link: {
                    mobileWebUrl: url,
                    webUrl: url,
                },
            },
            buttons: [
                {
                    title: buttonText,
                    link: {
                        mobileWebUrl: url,
                        webUrl: url,
                    },
                },
            ],
        });
    },

    /**
     * 청구서 카카오톡 공유 (Commerce 템플릿)
     * @param {Object} params
     * @param {string} params.title - 청구서 제목
     * @param {number} params.amount - 청구 금액
     * @param {string} [params.description] - 설명
     * @param {string} [params.dueDate] - 납부 기한
     * @param {string} [params.paymentUrl] - 결제 페이지 URL
     */
    shareInvoice({ title, amount, description, dueDate, paymentUrl }) {
        if (!this.isReady()) {
            alert('카카오톡 공유 기능을 사용할 수 없습니다.\nKAKAO_CLIENT_ID 설정을 확인해주세요.');
            return;
        }

        const baseUrl = window.location.origin;
        const url = paymentUrl || baseUrl + '/api/club/';
        const desc = description
            || (dueDate ? '납부 기한: ' + dueDate : 'FencingMind Club 청구서');

        Kakao.Share.sendDefault({
            objectType: 'commerce',
            content: {
                title: title,
                description: desc.substring(0, 200),
                imageUrl: baseUrl + '/static/icons/icon-512x512.png',
                link: {
                    mobileWebUrl: url,
                    webUrl: url,
                },
            },
            commerce: {
                regularPrice: amount,
                currencyUnit: '원',
                currencyUnitPosition: 1,
            },
            buttons: [
                {
                    title: '납부하기',
                    link: {
                        mobileWebUrl: url,
                        webUrl: url,
                    },
                },
            ],
        });
    },

    /**
     * 출석 알림 카카오톡 공유
     * @param {Object} params
     * @param {string} params.studentName - 학생 이름
     * @param {string} params.checkinTime - 체크인 시간
     * @param {string} params.clubName - 클럽 이름
     */
    shareCheckinNotice({ studentName, checkinTime, clubName }) {
        if (!this.isReady()) {
            alert('카카오톡 공유 기능을 사용할 수 없습니다.');
            return;
        }

        const baseUrl = window.location.origin;

        Kakao.Share.sendDefault({
            objectType: 'feed',
            content: {
                title: clubName + ' 출석 알림',
                description: studentName + '님이 ' + checkinTime + '에 체크인했습니다.',
                imageUrl: baseUrl + '/static/icons/icon-512x512.png',
                link: {
                    mobileWebUrl: baseUrl + '/api/club/',
                    webUrl: baseUrl + '/api/club/',
                },
            },
            buttons: [
                {
                    title: '출석 현황 보기',
                    link: {
                        mobileWebUrl: baseUrl + '/api/club/',
                        webUrl: baseUrl + '/api/club/',
                    },
                },
            ],
        });
    },

    /**
     * 일반 텍스트 카카오톡 공유
     * @param {Object} params
     * @param {string} params.title - 제목
     * @param {string} params.description - 설명
     * @param {string} [params.buttonText] - 버튼 텍스트
     * @param {string} [params.url] - 링크 URL
     */
    shareText({ title, description, buttonText = '자세히 보기', url }) {
        if (!this.isReady()) {
            alert('카카오톡 공유 기능을 사용할 수 없습니다.');
            return;
        }

        const baseUrl = window.location.origin;
        const linkUrl = url || baseUrl + '/api/club/';

        Kakao.Share.sendDefault({
            objectType: 'text',
            text: title + '\n\n' + description,
            link: {
                mobileWebUrl: linkUrl,
                webUrl: linkUrl,
            },
            buttons: [
                {
                    title: buttonText,
                    link: {
                        mobileWebUrl: linkUrl,
                        webUrl: linkUrl,
                    },
                },
            ],
        });
    },
};
