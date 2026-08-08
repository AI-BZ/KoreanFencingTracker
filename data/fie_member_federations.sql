-- ============================================================================
-- FIE (Federation Internationale d'Escrime) Member Federations
-- Complete list of all national fencing federations
-- Generated: 2026-05-24
-- Source: FIE official website (fie.org), confederation websites, Wikipedia
-- ============================================================================

-- ============================================================================
-- PART 1: Continental Confederations
-- ============================================================================

CREATE TABLE IF NOT EXISTS fie_confederations (
    id SERIAL PRIMARY KEY,
    code VARCHAR(5) NOT NULL UNIQUE,
    name_en VARCHAR(200) NOT NULL,
    name_fr VARCHAR(200),
    abbreviation VARCHAR(10) NOT NULL,
    website VARCHAR(200),
    headquarters VARCHAR(200),
    founded_year INTEGER,
    member_count INTEGER
);

INSERT INTO fie_confederations (code, name_en, name_fr, abbreviation, website, headquarters, founded_year, member_count)
VALUES
('EUR', 'European Fencing Confederation', 'Confédération Européenne d''Escrime', 'EFC/CEE', 'https://www.fencing-efc.eu', 'Brussels, Belgium', 1991, 47),
('AME', 'Pan American Fencing Confederation', 'Confédération Panaméricaine d''Escrime', 'CPE/PAFC', 'http://www.cpe-fie.org', 'Mexico City, Mexico', 1951, 33),
('AFR', 'African Fencing Confederation', 'Confédération Africaine d''Escrime', 'CAE', 'https://www.cae-fencing.org', 'Dakar, Senegal', 1989, 31),
('ASI', 'Fencing Confederation of Asia', 'Confédération Asiatique d''Escrime', 'FCA', 'https://asian-fencing.com', 'Kuwait City, Kuwait', 1988, 40),
('OCE', 'Oceania Fencing Confederation', 'Confédération d''Escrime d''Océanie', 'OFC', 'https://www.oceaniafencing.org', 'Sydney, Australia', 2002, 6);


-- ============================================================================
-- PART 2: National Federations
-- ============================================================================

CREATE TABLE IF NOT EXISTS fie_national_federations (
    id SERIAL PRIMARY KEY,
    -- Country identification
    country_name_en VARCHAR(100) NOT NULL,
    country_name_native VARCHAR(200),
    fie_code VARCHAR(5) NOT NULL UNIQUE,       -- FIE/IOC 3-letter code
    iso_alpha3 VARCHAR(3),                      -- ISO 3166-1 alpha-3
    -- Federation details
    federation_name_en VARCHAR(300),
    federation_name_native VARCHAR(300),
    federation_abbreviation VARCHAR(20),
    website VARCHAR(300),
    email VARCHAR(200),
    -- Classification
    confederation_code VARCHAR(5) NOT NULL REFERENCES fie_confederations(code),
    membership_status VARCHAR(20) DEFAULT 'full',  -- full, associate, suspended
    -- Metadata
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- ============================================================================
-- EUROPE (EFC/CEE) - 47 member federations
-- ============================================================================

INSERT INTO fie_national_federations (fie_code, iso_alpha3, country_name_en, country_name_native, federation_name_en, federation_name_native, federation_abbreviation, website, email, confederation_code, membership_status)
VALUES
-- Albania
('ALB', 'ALB', 'Albania', 'Shqipëria', 'Albanian Fencing Federation', 'Federata Shqiptare e Skermës', 'FSHSK', NULL, NULL, 'EUR', 'full'),
-- Armenia
('ARM', 'ARM', 'Armenia', 'Hayastan', 'Armenian Fencing Federation', NULL, NULL, NULL, NULL, 'EUR', 'full'),
-- Austria
('AUT', 'AUT', 'Austria', 'Österreich', 'Austrian Fencing Federation', 'Österreichischer Fechtverband', 'OeFV', 'http://www.oefv.com', 'office@oefv.com', 'EUR', 'full'),
-- Azerbaijan
('AZE', 'AZE', 'Azerbaijan', 'Azərbaycan', 'Azerbaijan Fencing Federation', 'Azərbaycan Qılıncoynatma Federasiyası', NULL, NULL, NULL, 'EUR', 'full'),
-- Belarus (suspended)
('BLR', 'BLR', 'Belarus', 'Беларусь', 'Belarusian Fencing Federation', 'Беларуская федэрацыя фехтавання', 'BFF', NULL, NULL, 'EUR', 'suspended'),
-- Belgium
('BEL', 'BEL', 'Belgium', 'België / Belgique', 'Royal Belgian Fencing Federation', 'Fédération Royale Belge des Cercles d''Escrime', 'FRBCE', 'http://www.fencing-belgium.be', 'info@fencing-belgium.be', 'EUR', 'full'),
-- Bulgaria
('BUL', 'BGR', 'Bulgaria', 'България', 'Bulgarian Fencing Federation', 'Българска федерация по фехтовка', 'BFF', NULL, NULL, 'EUR', 'full'),
-- Croatia
('CRO', 'HRV', 'Croatia', 'Hrvatska', 'Croatian Fencing Federation', 'Hrvatski mačevalački savez', 'HMS', NULL, NULL, 'EUR', 'full'),
-- Cyprus
('CYP', 'CYP', 'Cyprus', 'Κύπρος', 'Cyprus Fencing Federation', 'Κυπριακή Ομοσπονδία Ξιφασκίας', NULL, NULL, NULL, 'EUR', 'full'),
-- Czechia
('CZE', 'CZE', 'Czechia', 'Česko', 'Czech Fencing Federation', 'Český svaz šermu', 'CSS', NULL, NULL, 'EUR', 'full'),
-- Denmark
('DEN', 'DNK', 'Denmark', 'Danmark', 'Danish Fencing Federation', 'Dansk Fægte Forbund', 'DFF', 'http://www.faegtning.dk', 'dff@faegtning.dk', 'EUR', 'full'),
-- Estonia
('EST', 'EST', 'Estonia', 'Eesti', 'Estonian Fencing Federation', 'Eesti Vehklemisliit', 'EVL', NULL, NULL, 'EUR', 'full'),
-- Finland
('FIN', 'FIN', 'Finland', 'Suomi', 'Finnish Fencing Federation', 'Suomen Miekkailuliitto', 'SML', NULL, NULL, 'EUR', 'full'),
-- France
('FRA', 'FRA', 'France', 'France', 'French Fencing Federation', 'Fédération Française d''Escrime', 'FFE', 'http://www.escrime-ffe.fr', 'contact@ffescrime.fr', 'EUR', 'full'),
-- Georgia
('GEO', 'GEO', 'Georgia', 'საქართველო', 'Georgian Fencing Federation', 'საქართველოს ფარიკაობის ფედერაცია', NULL, NULL, NULL, 'EUR', 'full'),
-- Germany
('GER', 'DEU', 'Germany', 'Deutschland', 'German Fencing Federation', 'Deutscher Fechter-Bund', 'DFeB', 'http://www.fechten.org', 'info@fechten.org', 'EUR', 'full'),
-- Great Britain
('GBR', 'GBR', 'Great Britain', 'Great Britain', 'British Fencing', 'British Fencing Association', 'BF', 'http://www.britishfencing.com', 'headoffice@britishfencing.com', 'EUR', 'full'),
-- Greece
('GRE', 'GRC', 'Greece', 'Ελλάδα', 'Hellenic Fencing Federation', 'Ελληνική Ομοσπονδία Ξιφασκίας', 'EOX', 'http://www.fencing.org.gr', 'fencing@fencing.org.gr', 'EUR', 'full'),
-- Hungary
('HUN', 'HUN', 'Hungary', 'Magyarország', 'Hungarian Fencing Federation', 'Magyar Vívó Szövetség', 'MVSz', 'http://www.hunfencing.hu', 'benedek.soproniszabo@hunfencing.hu', 'EUR', 'full'),
-- Iceland
('ISL', 'ISL', 'Iceland', 'Ísland', 'Icelandic Fencing Federation', 'Skylmingasamband Íslands', NULL, NULL, NULL, 'EUR', 'full'),
-- Ireland
('IRL', 'IRL', 'Ireland', 'Éire', 'Fencing Ireland', 'Fencing Ireland', 'FI', NULL, NULL, 'EUR', 'full'),
-- Israel
('ISR', 'ISR', 'Israel', 'ישראל', 'Israel Fencing Association', 'איגוד הסיוף בישראל', 'IFA', 'http://www.fencing.org.il', 'office@fencing.org.il', 'EUR', 'full'),
-- Italy
('ITA', 'ITA', 'Italy', 'Italia', 'Italian Fencing Federation', 'Federazione Italiana Scherma', 'FIS', 'http://www.federscherma.it', 'internazionale@federscherma.it', 'EUR', 'full'),
-- Latvia
('LAT', 'LVA', 'Latvia', 'Latvija', 'Latvian Fencing Federation', 'Latvijas Paukošanas Federācija', 'LPF', NULL, NULL, 'EUR', 'full'),
-- Liechtenstein
('LIE', 'LIE', 'Liechtenstein', 'Liechtenstein', 'Liechtenstein Fencing Federation', 'Liechtensteiner Fechtverband', NULL, NULL, NULL, 'EUR', 'full'),
-- Lithuania
('LTU', 'LTU', 'Lithuania', 'Lietuva', 'Lithuanian Fencing Federation', 'Lietuvos fechtavimo federacija', 'LFF', NULL, NULL, 'EUR', 'full'),
-- Luxembourg
('LUX', 'LUX', 'Luxembourg', 'Lëtzebuerg', 'Luxembourg Fencing Federation', 'Fédération Luxembourgeoise d''Escrime', 'FLE', NULL, NULL, 'EUR', 'full'),
-- Malta
('MLT', 'MLT', 'Malta', 'Malta', 'Malta Fencing Association', 'Malta Fencing Association', 'MFA', NULL, NULL, 'EUR', 'full'),
-- Monaco
('MON', 'MCO', 'Monaco', 'Monaco', 'Fencing Federation of Monaco', 'Fédération Monégasque d''Escrime', 'FME', NULL, NULL, 'EUR', 'full'),
-- Montenegro
('MNE', 'MNE', 'Montenegro', 'Crna Gora', 'Fencing Federation of Montenegro', 'Mačevalački savez Crne Gore', NULL, NULL, NULL, 'EUR', 'full'),
-- Netherlands
('NED', 'NLD', 'Netherlands', 'Nederland', 'Royal Netherlands Fencing Federation', 'Koninklijke Nederlandse Algemene Schermbond', 'KNAS', 'http://www.knas.nl', 'info@knas.nl', 'EUR', 'full'),
-- North Macedonia
('MKD', 'MKD', 'North Macedonia', 'Северна Македонија', 'Fencing Federation of North Macedonia', 'Федерација на мечувалство на Македонија', NULL, NULL, NULL, 'EUR', 'full'),
-- Norway
('NOR', 'NOR', 'Norway', 'Norge', 'Norwegian Fencing Federation', 'Norges Fekteforbund', 'NFF', 'http://www.fekting.no', 'claes.bendiksen@nif.idrett.no', 'EUR', 'full'),
-- Poland
('POL', 'POL', 'Poland', 'Polska', 'Polish Fencing Federation', 'Polski Związek Szermierczy', 'PZSzerm', 'http://www.pzszerm.pl', 'pzszerm@pzszerm.pl', 'EUR', 'full'),
-- Portugal
('POR', 'PRT', 'Portugal', 'Portugal', 'Portuguese Fencing Federation', 'Federação Portuguesa de Esgrima', 'FPE', NULL, NULL, 'EUR', 'full'),
-- Moldova
('MDA', 'MDA', 'Moldova', 'Moldova', 'Fencing Federation of Moldova', 'Federația de Scrimă din Moldova', NULL, NULL, NULL, 'EUR', 'full'),
-- Romania
('ROU', 'ROU', 'Romania', 'România', 'Romanian Fencing Federation', 'Federația Română de Scrimă', 'FRS', 'http://www.frscrima.ro', 'office@frscrima.ro', 'EUR', 'full'),
-- Russia (suspended)
('RUS', 'RUS', 'Russia', 'Россия', 'Russian Fencing Federation', 'Федерация фехтования России', 'FFR', 'http://www.rusfencing.ru', 'info@rusfencing.ru', 'EUR', 'suspended'),
-- San Marino
('SMR', 'SMR', 'San Marino', 'San Marino', 'San Marino Fencing Federation', 'Federazione Sammarinese Scherma', 'FSS', NULL, NULL, 'EUR', 'full'),
-- Serbia
('SRB', 'SRB', 'Serbia', 'Србија', 'Fencing Federation of Serbia', 'Мачевалачки савез Србије', 'MSS', NULL, NULL, 'EUR', 'full'),
-- Slovakia
('SVK', 'SVK', 'Slovakia', 'Slovensko', 'Slovak Fencing Federation', 'Slovenský šermiársky zväz', 'SSZ', NULL, NULL, 'EUR', 'full'),
-- Slovenia
('SLO', 'SVN', 'Slovenia', 'Slovenija', 'Fencing Federation of Slovenia', 'Mečevalska zveza Slovenije', 'MZS', NULL, NULL, 'EUR', 'full'),
-- Spain
('ESP', 'ESP', 'Spain', 'España', 'Royal Spanish Fencing Federation', 'Real Federación Española de Esgrima', 'RFEE', 'http://www.esgrima.es', 'rfee@esgrima.es', 'EUR', 'full'),
-- Sweden
('SWE', 'SWE', 'Sweden', 'Sverige', 'Swedish Fencing Federation', 'Svenska Fäktförbundet', 'SFF', 'http://www.fencing.se', 'info@fencing.se', 'EUR', 'full'),
-- Switzerland
('SUI', 'CHE', 'Switzerland', 'Schweiz / Suisse', 'Swiss Fencing Federation', 'Fédération Suisse d''Escrime', 'FSE', 'http://www.swiss-fencing.ch', 'info@swiss-fencing.ch', 'EUR', 'full'),
-- Turkiye
('TUR', 'TUR', 'Turkiye', 'Türkiye', 'Turkish Fencing Federation', 'Türkiye Eskrim Federasyonu', 'TEF', 'http://www.eskrim.org.tr', 'tef@eskrim.org.tr', 'EUR', 'full'),
-- Ukraine
('UKR', 'UKR', 'Ukraine', 'Україна', 'Ukrainian Fencing Federation', 'Національна федерація фехтування України', 'NFFU', 'http://www.nffu.org.ua', 'ukr-fencing@ukr.net', 'EUR', 'full');

-- ============================================================================
-- ASIA (FCA) - 40 member federations
-- ============================================================================

INSERT INTO fie_national_federations (fie_code, iso_alpha3, country_name_en, country_name_native, federation_name_en, federation_name_native, federation_abbreviation, website, email, confederation_code, membership_status)
VALUES
-- Afghanistan
('AFG', 'AFG', 'Afghanistan', 'افغانستان', 'Fencing Federation of Afghanistan', 'فدراسیون شمشیرزنی افغانستان', NULL, NULL, 'fencing.afg@gmail.com', 'ASI', 'full'),
-- Bahrain
('BRN', 'BHR', 'Bahrain', 'البحرين', 'Bahrain Fencing Federation', 'الاتحاد البحريني للمبارزة', NULL, NULL, 'bahrainfencing@gmail.com', 'ASI', 'full'),
-- Bangladesh
('BAN', 'BGD', 'Bangladesh', 'বাংলাদেশ', 'Bangladesh Fencing Federation', 'বাংলাদেশ ফেন্সিং ফেডারেশন', 'BFF', 'http://www.fencingbangladesh.org', 'bangladeshfencing1171@gmail.com', 'ASI', 'full'),
-- Brunei Darussalam
('BRU', 'BRN', 'Brunei Darussalam', 'بروناي', 'Brunei Darussalam Fencing Federation', NULL, 'BDFF', 'http://www.bruneifencing.org', 'bdff.fencing@gmail.com', 'ASI', 'full'),
-- Cambodia
('CAM', 'KHM', 'Cambodia', 'កម្ពុជា', 'Cambodia Fencing Federation', 'សហព័ន្ធកាំបិត កម្ពុជា', 'CFF', 'http://www.camfencing.org', 'info@camfencing.org', 'ASI', 'full'),
-- China
('CHN', 'CHN', 'China', '中国', 'Chinese Fencing Association', '中国击剑协会', 'CFA', 'http://fencing.sport.org.cn', 'fencing@sports.cn', 'ASI', 'full'),
-- Chinese Taipei
('TPE', 'TWN', 'Chinese Taipei', '中華台北', 'Chinese Taipei Fencing Association', '中華民國擊劍協會', 'CTFA', NULL, 'taipei.fencing@msa.hinet.net', 'ASI', 'full'),
-- Hong Kong, China
('HKG', 'HKG', 'Hong Kong, China', '香港', 'Fencing Association of Hong Kong, China', '中國香港劍擊總會', 'HKFA', 'http://www.hkfa.org.hk', 'info@hkfa.org.hk', 'ASI', 'full'),
-- India
('IND', 'IND', 'India', 'भारत', 'Fencing Association of India', NULL, 'FAI', 'http://www.fencingindia.org', 'comm@fencingindia.org', 'ASI', 'full'),
-- Indonesia
('INA', 'IDN', 'Indonesia', 'Indonesia', 'Indonesian Fencing Federation', 'Ikatan Anggar Seluruh Indonesia', 'IKASI', 'http://www.ikasi.org', 'ikasiindonesia@gmail.com', 'ASI', 'full'),
-- Iran
('IRI', 'IRN', 'Iran', 'ایران', 'Iran Fencing Federation', 'فدراسیون شمشیربازی ایران', NULL, NULL, 'fencingiranfed@gmail.com', 'ASI', 'full'),
-- Iraq
('IRQ', 'IRQ', 'Iraq', 'العراق', 'Iraq Fencing Federation', 'الاتحاد العراقي للمبارزة', NULL, NULL, 'Fencing_iraq@yahoo.com', 'ASI', 'full'),
-- Japan
('JPN', 'JPN', 'Japan', '日本', 'Japan Fencing Association', '日本フェンシング協会', 'JFA', 'http://www.fencing-jpn.jp', 'info@fencing-jpn.jp', 'ASI', 'full'),
-- Jordan
('JOR', 'JOR', 'Jordan', 'الأردن', 'Jordan Fencing Federation', 'الاتحاد الأردني للمبارزة', NULL, 'http://www.fencingjordan.com', 'jofenc@hotmail.com', 'ASI', 'full'),
-- Kazakhstan
('KAZ', 'KAZ', 'Kazakhstan', 'Қазақстан', 'Kazakhstan Fencing Federation', 'Қазақстан семсерлесу федерациясы', NULL, 'http://www.kazfencing.com', 'office@kazfencing.com', 'ASI', 'full'),
-- Korea
('KOR', 'KOR', 'Korea', '대한민국', 'Korea Fencing Federation', '대한펜싱협회', 'KFF', 'http://fencing.sports.or.kr', 'kffseoul@hotmail.com', 'ASI', 'full'),
-- North Korea
('PRK', 'PRK', 'North Korea', '조선민주주의인민공화국', 'DPR Korea Fencing Association', '조선민주주의인민공화국 펜싱 협회', NULL, NULL, NULL, 'ASI', 'full'),
-- Kuwait
('KUW', 'KWT', 'Kuwait', 'الكويت', 'Kuwait Fencing Amateur Association', 'الاتحاد الكويتي للمبارزة', NULL, 'http://www.q8-fencing.com', 'info@fencingkw.com', 'ASI', 'full'),
-- Kyrgyzstan
('KGZ', 'KGZ', 'Kyrgyzstan', 'Кыргызстан', 'Kyrgyz Fencing Federation', 'Кыргыз фехтование федерациясы', NULL, NULL, 'kgz.fencing@gmail.com', 'ASI', 'full'),
-- Lebanon
('LBN', 'LBN', 'Lebanon', 'لبنان', 'Lebanon Fencing Federation', 'الاتحاد اللبناني للمبارزة', NULL, NULL, 'fencinglebanon@yahoo.com', 'ASI', 'full'),
-- Macao, China
('MAC', 'MAC', 'Macao, China', '澳門', 'Macao Fencing Association', '澳門劍擊總會', NULL, NULL, 'fencingmo@yahoo.com', 'ASI', 'full'),
-- Malaysia
('MAS', 'MYS', 'Malaysia', 'Malaysia', 'Malaysian Fencing Federation', 'Persekutuan Anggar Malaysia', 'MFF', NULL, 'mffmalaysia@hotmail.com', 'ASI', 'full'),
-- Mongolia
('MGL', 'MNG', 'Mongolia', 'Монгол', 'Mongolia Fencing Federation', 'Монголын илдний спортын холбоо', NULL, NULL, 'mongolia@fencing.mn', 'ASI', 'full'),
-- Myanmar
('MYA', 'MMR', 'Myanmar', 'မြန်မာ', 'Myanmar Fencing Federation', NULL, NULL, NULL, 'fencingmyanmar@gmail.com', 'ASI', 'full'),
-- Nepal
('NEP', 'NPL', 'Nepal', 'नेपाल', 'Nepal Fencing Association', 'नेपाल फेन्सिङ एसोसिएसन', 'NFA', NULL, 'nepalfencing@gmail.com', 'ASI', 'full'),
-- Oman
('OMA', 'OMN', 'Oman', 'عُمان', 'Oman Fencing Committee', 'لجنة المبارزة العمانية', NULL, NULL, NULL, 'ASI', 'full'),
-- Pakistan
('PAK', 'PAK', 'Pakistan', 'پاکستان', 'Pakistan Fencing Federation', NULL, 'PFF', 'http://www.fencing.pk', 'pakistanfencingfederation1@gmail.com', 'ASI', 'full'),
-- Palestine
('PLE', 'PSE', 'Palestine', 'فلسطين', 'Palestine Fencing Federation', 'الاتحاد الفلسطيني للمبارزة', NULL, NULL, 'ffpal@yahoo.com', 'ASI', 'full'),
-- Philippines
('PHI', 'PHL', 'Philippines', 'Pilipinas', 'Philippine Fencing Association', NULL, 'PFA', NULL, 'philfencing@gmail.com', 'ASI', 'full'),
-- Qatar
('QAT', 'QAT', 'Qatar', 'قطر', 'Qatar Fencing Federation', 'الاتحاد القطري للمبارزة', 'QFF', 'http://www.qatarfencing.qa', 'qff@olympic.qa', 'ASI', 'full'),
-- Saudi Arabia
('KSA', 'SAU', 'Saudi Arabia', 'المملكة العربية السعودية', 'Saudi Arabia Fencing Federation', 'الاتحاد السعودي للمبارزة', NULL, 'http://www.fencing.sa', 'info@fencing.sa', 'ASI', 'full'),
-- Singapore
('SGP', 'SGP', 'Singapore', 'Singapore', 'Fencing Singapore', NULL, 'FS', 'http://www.fencingsingapore.org.sg', 'fsgm@fencingsingapore.org.sg', 'ASI', 'full'),
-- Sri Lanka
('SRI', 'LKA', 'Sri Lanka', 'ශ්‍රී ලංකාව', 'Sri Lanka Fencing Federation', NULL, 'SLFF', NULL, 'fencing.srilanka@gmail.com', 'ASI', 'full'),
-- Syria
('SYR', 'SYR', 'Syrian Arab Republic', 'سوريا', 'Syrian Fencing Federation', 'الاتحاد السوري للمبارزة', NULL, NULL, 'fencing.syr@gmail.com', 'ASI', 'full'),
-- Tajikistan
('TJK', 'TJK', 'Tajikistan', 'Тоҷикистон', 'Tajikistan Fencing Federation', NULL, NULL, NULL, NULL, 'ASI', 'full'),
-- Thailand
('THA', 'THA', 'Thailand', 'ประเทศไทย', 'Thailand Fencing Association', 'สมาคมกีฬาฟันดาบแห่งประเทศไทย', 'TFA', 'http://www.thaifencing.org', 'fencing.tha@gmail.com', 'ASI', 'full'),
-- Turkmenistan
('TKM', 'TKM', 'Turkmenistan', 'Türkmenistan', 'Turkmenistan Fencing Federation', NULL, NULL, NULL, NULL, 'ASI', 'full'),
-- United Arab Emirates
('UAE', 'ARE', 'United Arab Emirates', 'الإمارات', 'UAE Fencing Federation', 'اتحاد الإمارات للمبارزة', NULL, NULL, NULL, 'ASI', 'full'),
-- Uzbekistan
('UZB', 'UZB', 'Uzbekistan', 'Oʻzbekiston', 'Uzbekistan Fencing Federation', NULL, NULL, NULL, NULL, 'ASI', 'full'),
-- Vietnam
('VIE', 'VNM', 'Vietnam', 'Việt Nam', 'Vietnam Fencing Federation', 'Liên đoàn Đấu kiếm Việt Nam', NULL, NULL, NULL, 'ASI', 'full'),
-- Yemen
('YEM', 'YEM', 'Yemen', 'اليمن', 'Yemen Fencing Federation', 'الاتحاد اليمني للمبارزة', NULL, NULL, NULL, 'ASI', 'full');

-- ============================================================================
-- AMERICAS (CPE/PAFC) - 33 member federations
-- ============================================================================

INSERT INTO fie_national_federations (fie_code, iso_alpha3, country_name_en, country_name_native, federation_name_en, federation_name_native, federation_abbreviation, website, email, confederation_code, membership_status)
VALUES
-- Antigua and Barbuda
('ANT', 'ATG', 'Antigua and Barbuda', NULL, 'Antigua and Barbuda Fencing Association', NULL, NULL, NULL, NULL, 'AME', 'full'),
-- Argentina
('ARG', 'ARG', 'Argentina', 'Argentina', 'Argentine Fencing Federation', 'Federación Argentina de Esgrima', 'FAE', 'http://www.esgrima-fae.com.ar', 'presidencia@faesgrima.org', 'AME', 'full'),
-- Aruba
('ARU', 'ABW', 'Aruba', 'Aruba', 'Aruba Fencing Federation', 'Aruba Fencing Bond', NULL, NULL, NULL, 'AME', 'full'),
-- Bahamas
('BAH', 'BHS', 'Bahamas', 'Bahamas', 'Bahamas Fencing Federation', NULL, NULL, NULL, NULL, 'AME', 'full'),
-- Barbados
('BAR', 'BRB', 'Barbados', 'Barbados', 'Barbados Fencing Association', NULL, NULL, NULL, NULL, 'AME', 'full'),
-- Belize
('BIZ', 'BLZ', 'Belize', 'Belize', 'Belize Fencing Federation', NULL, NULL, NULL, NULL, 'AME', 'full'),
-- Bermuda
('BER', 'BMU', 'Bermuda', 'Bermuda', 'Bermuda Fencing Federation', NULL, NULL, NULL, NULL, 'AME', 'full'),
-- Bolivia
('BOL', 'BOL', 'Bolivia', 'Bolivia', 'Bolivian Fencing Federation', 'Federación Boliviana de Esgrima', NULL, NULL, NULL, 'AME', 'full'),
-- Brazil
('BRA', 'BRA', 'Brazil', 'Brasil', 'Brazilian Fencing Confederation', 'Confederação Brasileira de Esgrima', 'CBE', 'http://www.cbesgrima.org.br', 'contato@cbesgrima.org.br', 'AME', 'full'),
-- Canada
('CAN', 'CAN', 'Canada', 'Canada', 'Canadian Fencing Federation', 'Fédération Canadienne d''Escrime', 'CFF', 'http://www.fencing.ca', 'president@fencing.ca', 'AME', 'full'),
-- Chile
('CHI', 'CHL', 'Chile', 'Chile', 'Chilean Fencing Federation', 'Federación Chilena de Esgrima', 'FECHILE', 'http://www.esgrima.cl', 'esgrimachi@gmail.com', 'AME', 'full'),
-- Colombia
('COL', 'COL', 'Colombia', 'Colombia', 'Colombian Fencing Federation', 'Federación Colombiana de Esgrima', 'FCE', 'http://www.colombiaesgrima.es', 'fcesgrimacol@gmail.com', 'AME', 'full'),
-- Costa Rica
('CRC', 'CRI', 'Costa Rica', 'Costa Rica', 'Costa Rica Fencing Federation', 'Federación Costarricense de Esgrima', NULL, NULL, NULL, 'AME', 'full'),
-- Cuba
('CUB', 'CUB', 'Cuba', 'Cuba', 'Cuban Fencing Federation', 'Federación Cubana de Esgrima', NULL, 'http://www.inder.co.cu', 'federacioncubanadeesgrima@gmail.com', 'AME', 'full'),
-- Dominica
('DMA', 'DMA', 'Dominica', 'Dominica', 'Dominica Fencing Association', NULL, NULL, NULL, NULL, 'AME', 'full'),
-- Dominican Republic
('DOM', 'DOM', 'Dominican Republic', 'República Dominicana', 'Dominican Fencing Federation', 'Federación Dominicana de Esgrima', NULL, NULL, NULL, 'AME', 'full'),
-- Ecuador
('ECU', 'ECU', 'Ecuador', 'Ecuador', 'Ecuadorian Fencing Federation', 'Federación Ecuatoriana de Esgrima', 'FEE', NULL, NULL, 'AME', 'full'),
-- El Salvador
('ESA', 'SLV', 'El Salvador', 'El Salvador', 'Salvadoran Fencing Federation', 'Federación Salvadoreña de Esgrima', NULL, NULL, NULL, 'AME', 'full'),
-- Guatemala
('GUA', 'GTM', 'Guatemala', 'Guatemala', 'Guatemalan Fencing Federation', 'Asociación Nacional de Esgrima de Guatemala', NULL, NULL, NULL, 'AME', 'full'),
-- Guyana
('GUY', 'GUY', 'Guyana', 'Guyana', 'Guyana Fencing Association', NULL, NULL, NULL, NULL, 'AME', 'full'),
-- Haiti
('HAI', 'HTI', 'Haiti', 'Haïti', 'Haitian Fencing Federation', 'Fédération Haïtienne d''Escrime', NULL, NULL, NULL, 'AME', 'full'),
-- Honduras
('HON', 'HND', 'Honduras', 'Honduras', 'Honduran Fencing Federation', 'Federación Hondureña de Esgrima', NULL, NULL, NULL, 'AME', 'full'),
-- Jamaica
('JAM', 'JAM', 'Jamaica', 'Jamaica', 'Jamaica Fencing Association', NULL, NULL, NULL, NULL, 'AME', 'full'),
-- Mexico
('MEX', 'MEX', 'Mexico', 'México', 'Mexican Fencing Federation', 'Federación Mexicana de Esgrima', 'FME', 'http://www.femexesgrima.net', 'fme.esgrima@gmail.com', 'AME', 'full'),
-- Nicaragua
('NCA', 'NIC', 'Nicaragua', 'Nicaragua', 'Nicaraguan Fencing Federation', 'Federación Nicaragüense de Esgrima', NULL, NULL, NULL, 'AME', 'full'),
-- Panama
('PAN', 'PAN', 'Panama', 'Panamá', 'Panamanian Fencing Federation', 'Federación Panameña de Esgrima', NULL, NULL, NULL, 'AME', 'full'),
-- Paraguay
('PAR', 'PRY', 'Paraguay', 'Paraguay', 'Paraguayan Fencing Federation', 'Federación Paraguaya de Esgrima', NULL, NULL, NULL, 'AME', 'full'),
-- Peru
('PER', 'PER', 'Peru', 'Perú', 'Peruvian Fencing Federation', 'Federación Deportiva Nacional de Esgrima', 'FDNPE', NULL, 'presidencia@fdnpe.pe', 'AME', 'full'),
-- Puerto Rico
('PUR', 'PRI', 'Puerto Rico', 'Puerto Rico', 'Puerto Rico Fencing Federation', 'Federación Puertorriqueña de Esgrima', NULL, NULL, NULL, 'AME', 'full'),
-- Trinidad and Tobago
('TTO', 'TTO', 'Trinidad and Tobago', 'Trinidad and Tobago', 'Trinidad and Tobago Fencing Association', NULL, 'TTFA', NULL, NULL, 'AME', 'full'),
-- United States of America
('USA', 'USA', 'United States of America', NULL, 'USA Fencing', 'United States Fencing Association', 'USFA', 'http://www.USFencing.org', 'international@usfencing.org', 'AME', 'full'),
-- Uruguay
('URU', 'URY', 'Uruguay', 'Uruguay', 'Uruguayan Fencing Federation', 'Federación de Esgrima del Uruguay', NULL, NULL, NULL, 'AME', 'full'),
-- Venezuela
('VEN', 'VEN', 'Venezuela', 'Venezuela', 'Venezuelan Fencing Federation', 'Federación Venezolana de Esgrima', 'FVE', NULL, 'marin.f.ven@gmail.com', 'AME', 'full'),
-- Virgin Islands
('ISV', 'VIR', 'Virgin Islands', NULL, 'Virgin Islands Fencing Association', NULL, NULL, NULL, NULL, 'AME', 'full');

-- ============================================================================
-- AFRICA (CAE) - 31 member federations
-- ============================================================================

INSERT INTO fie_national_federations (fie_code, iso_alpha3, country_name_en, country_name_native, federation_name_en, federation_name_native, federation_abbreviation, website, email, confederation_code, membership_status)
VALUES
-- Algeria
('ALG', 'DZA', 'Algeria', 'الجزائر', 'Algerian Fencing Federation', 'Fédération Algérienne d''Escrime', 'FAE', NULL, 'faescrime@gmail.com', 'AFR', 'full'),
-- Angola
('ANG', 'AGO', 'Angola', 'Angola', 'Angolan Fencing Federation', 'Federação Angolana de Esgrima', NULL, NULL, NULL, 'AFR', 'full'),
-- Benin
('BEN', 'BEN', 'Benin', 'Bénin', 'Benin Fencing Association', 'Association Béninoise d''Escrime', 'ABE', NULL, NULL, 'AFR', 'full'),
-- Botswana
('BOT', 'BWA', 'Botswana', 'Botswana', 'Botswana Amateur Fencing Association', NULL, 'BAFA', NULL, NULL, 'AFR', 'full'),
-- Burkina Faso
('BUR', 'BFA', 'Burkina Faso', 'Burkina Faso', 'Burkina Faso Fencing Federation', 'Fédération Burkinabè d''Escrime', NULL, NULL, NULL, 'AFR', 'full'),
-- Cameroon
('CMR', 'CMR', 'Cameroon', 'Cameroun', 'Cameroon Fencing Federation', 'Fédération Camerounaise d''Escrime', 'FECAES', NULL, NULL, 'AFR', 'full'),
-- Cape Verde
('CPV', 'CPV', 'Cape Verde', 'Cabo Verde', 'Cape Verde Fencing Federation', 'Federação Caboverdiana de Esgrima', NULL, NULL, NULL, 'AFR', 'full'),
-- Congo
('CGO', 'COG', 'Congo', 'Congo', 'Congo Fencing Federation', 'Fédération Congolaise d''Escrime', NULL, NULL, NULL, 'AFR', 'full'),
-- Cote d'Ivoire
('CIV', 'CIV', 'Cote d''Ivoire', 'Côte d''Ivoire', 'Cote d''Ivoire Fencing Federation', 'Fédération Ivoirienne d''Escrime', 'FIE-CI', NULL, NULL, 'AFR', 'full'),
-- Democratic Republic of Congo
('COD', 'COD', 'Democratic Republic of Congo', 'République démocratique du Congo', 'DR Congo Fencing Federation', 'Fédération d''Escrime de la RD Congo', NULL, NULL, NULL, 'AFR', 'full'),
-- Egypt
('EGY', 'EGY', 'Egypt', 'مصر', 'Egyptian Fencing Federation', 'الاتحاد المصري للسلاح', 'EFF', 'http://www.fencingegypt.org', 'admin@fencingegypt.org', 'AFR', 'full'),
-- Equatorial Guinea
('GEQ', 'GNQ', 'Equatorial Guinea', 'Guinea Ecuatorial', 'Equatorial Guinea Fencing Federation', 'Federación Ecuatoguineana de Esgrima', NULL, NULL, NULL, 'AFR', 'full'),
-- Gabon
('GAB', 'GAB', 'Gabon', 'Gabon', 'Gabonese Fencing Federation', 'Fédération Gabonaise d''Escrime', NULL, NULL, NULL, 'AFR', 'full'),
-- Ghana
('GHA', 'GHA', 'Ghana', 'Ghana', 'Ghana Fencing Association', NULL, 'GFA', NULL, NULL, 'AFR', 'full'),
-- Guinea
('GUI', 'GIN', 'Guinea', 'Guinée', 'Guinea Fencing Federation', 'Fédération Guinéenne d''Escrime', NULL, NULL, NULL, 'AFR', 'full'),
-- Kenya
('KEN', 'KEN', 'Kenya', 'Kenya', 'Kenya Fencing Federation', NULL, NULL, NULL, NULL, 'AFR', 'full'),
-- Libya
('LBA', 'LBY', 'Libya', 'ليبيا', 'Libyan Fencing Federation', 'الاتحاد الليبي للمبارزة', NULL, NULL, NULL, 'AFR', 'full'),
-- Madagascar
('MAD', 'MDG', 'Madagascar', 'Madagasikara', 'Madagascar Fencing Federation', 'Fédération Malgache d''Escrime', NULL, NULL, NULL, 'AFR', 'full'),
-- Mali
('MLI', 'MLI', 'Mali', 'Mali', 'Mali Fencing Federation', 'Fédération Malienne d''Escrime', NULL, NULL, NULL, 'AFR', 'full'),
-- Mauritania
('MTN', 'MRT', 'Mauritania', 'موريتانيا', 'Mauritanian Fencing Federation', 'Fédération de Mauritanie d''Escrime', NULL, NULL, NULL, 'AFR', 'full'),
-- Mauritius
('MRI', 'MUS', 'Mauritius', 'Maurice', 'Mauritius Fencing Federation', 'Fédération d''Escrime de Maurice', NULL, NULL, NULL, 'AFR', 'full'),
-- Morocco
('MAR', 'MAR', 'Morocco', 'المغرب', 'Royal Moroccan Fencing Federation', 'Fédération Royale Marocaine d''Escrime', 'FRME', 'http://www.marocescrime.com', 'frme2010@gmail.com', 'AFR', 'full'),
-- Namibia
('NAM', 'NAM', 'Namibia', 'Namibia', 'Namibia Fencing Federation', NULL, NULL, NULL, NULL, 'AFR', 'full'),
-- Niger
('NIG', 'NER', 'Niger', 'Niger', 'Niger Fencing Federation', 'Fédération Nigérienne d''Escrime', NULL, NULL, NULL, 'AFR', 'full'),
-- Nigeria
('NGR', 'NGA', 'Nigeria', 'Nigeria', 'Fencing Federation of Nigeria', NULL, 'FFN', NULL, 'info@nigerianfencing.com', 'AFR', 'full'),
-- Rwanda
('RWA', 'RWA', 'Rwanda', 'Rwanda', 'Rwanda Fencing Federation', 'Fédération Rwandaise d''Escrime', NULL, NULL, NULL, 'AFR', 'full'),
-- Senegal
('SEN', 'SEN', 'Senegal', 'Sénégal', 'Senegalese Fencing Federation', 'Fédération Sénégalaise d''Escrime', 'FSE', NULL, 'fsescrimesenegal2018@gmail.com', 'AFR', 'full'),
-- Sierra Leone
('SLE', 'SLE', 'Sierra Leone', 'Sierra Leone', 'Sierra Leone Fencing Association', NULL, NULL, NULL, NULL, 'AFR', 'full'),
-- Somalia
('SOM', 'SOM', 'Somalia', 'Soomaaliya', 'Somalia Fencing Federation', NULL, NULL, NULL, NULL, 'AFR', 'full'),
-- South Africa
('RSA', 'ZAF', 'South Africa', 'South Africa', 'Fencing Federation of South Africa', NULL, 'FFSA', 'http://www.safencer.co.za', 'louise@safefencing.co.za', 'AFR', 'full'),
-- Sudan
('SUD', 'SDN', 'Sudan', 'السودان', 'Sudan Fencing Federation', 'الاتحاد السوداني للمبارزة', NULL, NULL, NULL, 'AFR', 'full'),
-- Togo
('TOG', 'TGO', 'Togo', 'Togo', 'Togolese Fencing Federation', 'Fédération Togolaise d''Escrime', NULL, NULL, NULL, 'AFR', 'full'),
-- Tunisia
('TUN', 'TUN', 'Tunisia', 'تونس', 'Tunisian Fencing Federation', 'Fédération Tunisienne d''Escrime', 'FTE', NULL, 'contact@ftescrime.com', 'AFR', 'full'),
-- Uganda
('UGA', 'UGA', 'Uganda', 'Uganda', 'Uganda Fencing Federation', NULL, 'UFF', NULL, NULL, 'AFR', 'full');

-- ============================================================================
-- OCEANIA (OFC) - 6 member federations
-- ============================================================================

INSERT INTO fie_national_federations (fie_code, iso_alpha3, country_name_en, country_name_native, federation_name_en, federation_name_native, federation_abbreviation, website, email, confederation_code, membership_status)
VALUES
-- Australia
('AUS', 'AUS', 'Australia', 'Australia', 'Australian Fencing Federation', NULL, 'AFF', 'http://www.ausfencing.org', 'president@fencing.org.au', 'OCE', 'full'),
-- Guam
('GUM', 'GUM', 'Guam', 'Guåhan', 'Guam Fencing Federation', NULL, NULL, NULL, NULL, 'OCE', 'full'),
-- New Zealand
('NZL', 'NZL', 'New Zealand', 'Aotearoa', 'Fencing New Zealand', NULL, 'FNZ', 'http://www.fencing.org.nz', 'secretary@fencing.org.nz', 'OCE', 'full'),
-- Samoa
('SAM', 'WSM', 'Samoa', 'Sāmoa', 'Samoa Fencing Association', NULL, NULL, NULL, NULL, 'OCE', 'full'),
-- American Samoa
('ASA', 'ASM', 'American Samoa', 'Amerika Sāmoa', 'American Samoa Fencing Association', NULL, NULL, NULL, NULL, 'OCE', 'associate'),
-- Papua New Guinea
('PNG', 'PNG', 'Papua New Guinea', 'Papua Niugini', 'Papua New Guinea Fencing Federation', NULL, NULL, NULL, NULL, 'OCE', 'associate');


-- ============================================================================
-- PART 3: Summary Counts and Verification
-- ============================================================================

-- Total count verification
-- Europe (EFC/CEE):  47 federations (including 2 suspended: Russia, Belarus; plus Liechtenstein)
-- Asia (FCA):        41 federations (including Hong Kong, Macao, Chinese Taipei, North Korea)
-- Americas (CPE):    34 federations (including territories: Puerto Rico, Virgin Islands, Aruba, Bermuda)
-- Africa (CAE):      34 federations (including Cape Verde, Kenya, Somalia, Sudan)
-- Oceania (OFC):      6 federations (including 2 associate: American Samoa, Papua New Guinea)
-- -------
-- TOTAL: 162 entries
-- Note: FIE officially counts ~155-157 "member federations" but this varies
-- by whether territories (HKG, MAC, TPE, PUR, ISV, ARU, BER, GUM, ASA) are
-- counted as separate members or grouped with parent nations.

-- Useful views
CREATE OR REPLACE VIEW fie_federations_summary AS
SELECT
    c.abbreviation AS confederation,
    c.name_en AS confederation_name,
    COUNT(f.id) AS total_members,
    COUNT(CASE WHEN f.membership_status = 'full' THEN 1 END) AS full_members,
    COUNT(CASE WHEN f.membership_status = 'suspended' THEN 1 END) AS suspended,
    COUNT(CASE WHEN f.membership_status = 'associate' THEN 1 END) AS associate
FROM fie_confederations c
LEFT JOIN fie_national_federations f ON f.confederation_code = c.code
GROUP BY c.abbreviation, c.name_en
ORDER BY total_members DESC;

-- Index for lookups
CREATE INDEX IF NOT EXISTS idx_fie_fed_fie_code ON fie_national_federations(fie_code);
CREATE INDEX IF NOT EXISTS idx_fie_fed_iso ON fie_national_federations(iso_alpha3);
CREATE INDEX IF NOT EXISTS idx_fie_fed_conf ON fie_national_federations(confederation_code);
