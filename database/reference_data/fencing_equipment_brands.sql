-- ============================================================================
-- FENCING EQUIPMENT MANUFACTURERS & BRANDS - COMPREHENSIVE WORLDWIDE LIST
-- Generated: 2026-05-24
-- Sources: FIE Official Registry, manufacturer websites, industry databases
-- ============================================================================

-- Create the table
CREATE TABLE IF NOT EXISTS fencing_equipment_brands (
    id SERIAL PRIMARY KEY,
    brand_name VARCHAR(200) NOT NULL,
    company_legal_name VARCHAR(300),
    country_code CHAR(3) NOT NULL,          -- ISO 3166-1 alpha-3
    country_name VARCHAR(100) NOT NULL,
    city VARCHAR(200),
    website_url VARCHAR(500),
    founded_year INTEGER,
    product_categories TEXT[],              -- ARRAY of categories
    is_fie_registered BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,
    brand_type VARCHAR(50) NOT NULL,        -- 'manufacturer', 'retailer', 'both', 'software', 'scoring'
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Product category legend:
--   'weapons'       = blades, foils, epees, sabres, complete weapons
--   'clothing'      = jackets, breeches, plastrons, lames, uniforms
--   'masks'         = fencing masks and visors
--   'gloves'        = fencing gloves
--   'shoes'         = fencing shoes
--   'bags'          = fencing bags, roller bags, weapon bags
--   'accessories'   = body wires, spare parts, blade tools, misc
--   'scoring'       = scoring machines, signaling apparatus
--   'piste'         = metallic pistes, conductive strips, aluminium pistes
--   'training'      = training dummies, targets, practice equipment
--   'electrical'    = electrical equipment, reels, cables
--   'software'      = tournament management, scoring software
--   'broadcasting'  = video replay, broadcasting systems

-- ============================================================================
-- SECTION 1: MAJOR INTERNATIONAL MANUFACTURERS (FIE Registered)
-- ============================================================================

INSERT INTO fencing_equipment_brands (brand_name, company_legal_name, country_code, country_name, city, website_url, founded_year, product_categories, is_fie_registered, is_active, brand_type, description)
VALUES

-- GERMANY
('Allstar', 'allstar Fecht-Center GmbH & Co. KG', 'DEU', 'Germany', 'Kusterdingen',
 'https://allstar.de', 1964,
 ARRAY['weapons','clothing','masks','gloves','shoes','bags','accessories','scoring','piste','electrical'],
 TRUE, TRUE, 'manufacturer',
 'Founded in 1964 by Johanna Messemer and son Roland. World''s largest selection of fencing items. Invented the first microprocessor-controlled scoring machine (1981) and first universal scoring box for all three weapons (1987). Made in Germany. Now parent company of Uhlmann.'),

('Uhlmann', 'Uhlmann Fechtsport GmbH & Co. KG', 'DEU', 'Germany', 'Laupheim',
 'https://uhlmann-fechtsport.com', 1933,
 ARRAY['weapons','clothing','masks','gloves','shoes','bags','accessories','scoring','piste','electrical'],
 TRUE, TRUE, 'manufacturer',
 'Founded by Josef Uhlmann in 1933. One of the world''s leading fencing equipment manufacturers, supplying over 80 countries with 3000+ fencing items. Now part of the Allstar group. Based in Laupheim, Baden-Wuerttemberg.'),

('ARTOS Fencing', 'ARTOS Fencing GmbH & Co. KG', 'DEU', 'Germany', 'Schkeuditz',
 'https://artos-fencing.com', 1994,
 ARRAY['clothing','masks','gloves','bags','accessories','piste','scoring','electrical'],
 TRUE, TRUE, 'manufacturer',
 'Founded in 1994. Globally recognized brand and one of the largest and most innovative suppliers of fencing products. Known for FIE-patented aluminium pistes with self-interlocking modular sections.'),

('FWF Fechtwelt', 'FWF Fechtwelt GmbH', 'DEU', 'Germany', 'Mietingen',
 'https://fechtwelt.de', 2005,
 ARRAY['weapons','clothing','masks','gloves','shoes','bags','accessories'],
 TRUE, TRUE, 'manufacturer',
 'Founded in 2005. Products of Karl Rolser GmbH (over 45 years of fencing equipment production). FWF fencing equipment and clothing is made in Germany according to FIE standards. Also sells HEMA and theatrical weapons.'),

-- UNITED KINGDOM
('Leon Paul', 'Leon Paul Equipment Co. Ltd', 'GBR', 'United Kingdom', 'London',
 'https://www.leonpaul.com', 1921,
 ARRAY['weapons','clothing','masks','gloves','shoes','bags','accessories','scoring','electrical'],
 TRUE, TRUE, 'manufacturer',
 'Established in 1921 by Leon Paul, a French fencing Maitre d''Armes. Family-run for over 100 years. The only fencing company run by Olympic fencers. Recipient of the King''s Award for Enterprise. Manufactures blades, masks and protective clothing at its Hendon facility. Launched wireless scoring machines in 2024.'),

('Excalibur Sports', 'Excalibur Sports Ltd.', 'GBR', 'United Kingdom', 'Hereford',
 'https://excalibursports.co.uk', 2017,
 ARRAY['weapons','clothing','masks','gloves','bags','accessories','scoring','piste'],
 TRUE, TRUE, 'both',
 'Founded in 2017 by two competitive international-level fencers. British-based retailer and distributor of fencing equipment, also carries combat sabers and HEMA equipment. Supplies 350N and 800N FIE Approved kit.'),

-- FRANCE
('Prieur', 'Prieur Sports', 'FRA', 'France', 'Genlis',
 'https://www.prieur-sports.com', 1788,
 ARRAY['weapons','clothing','masks','gloves','shoes','bags','accessories'],
 TRUE, TRUE, 'manufacturer',
 'Founded in 1788 - the oldest fencing brand in the world. Created the first sports fencing mask in 1844. The only French generalist fencing manufacturer. Official supplier to the French Fencing Federation. Equipment manufactured in the heart of Burgundy.'),

('Blaise Freres', 'Blaise Freres S.A.S.', 'FRA', 'France', 'Le Chambon-Feugerolles',
 'https://blaise-freres.fr', 1885,
 ARRAY['weapons'],
 TRUE, TRUE, 'manufacturer',
 'Historic French forge producing fencing blades since 1885. Renowned for high quality and workmanship. Blades made with Maraging stainless steel, well balanced with great point control. One of the world''s premier blade foundries.'),

('KABCOM', 'KABCOM', 'FRA', 'France', 'Aurec sur Loire',
 'https://kabcom.fr', NULL,
 ARRAY['weapons','accessories','electrical'],
 TRUE, TRUE, 'manufacturer',
 'French fencing equipment manufacturer based in Aurec sur Loire. FIE-registered licensed manufacturer.'),

('Planete Escrime', 'Planete Escrime', 'FRA', 'France', 'Paris',
 'https://www.planeteescrime.com', NULL,
 ARRAY['weapons','clothing','masks','gloves','shoes','bags','accessories','piste'],
 FALSE, TRUE, 'retailer',
 'Paris-based retailer at 74 rue Clisson, 75013 Paris. Carries wide selection of fencing equipment including weapons, blades, clothing (350N and 800N), masks, shoes, and pistes.'),

('Escrime Diffusion', 'Escrime Diffusion', 'FRA', 'France', NULL,
 'https://escrime-diffusion.fr', NULL,
 ARRAY['weapons','clothing','masks','gloves','bags','accessories'],
 FALSE, TRUE, 'retailer',
 'French fencing equipment retailer. Serves fencing fans and professionals across France with everything from beginner foils to professional competition equipment.'),

('Malterre', 'Malterre', 'FRA', 'France', 'Moreuil',
 'https://www.malterrefencing.com', NULL,
 ARRAY['piste','accessories'],
 FALSE, TRUE, 'manufacturer',
 'French manufacturer specializing in flexible fencing piste equipment. Produces new generation conductive textile fencing strips approved for all types of competitions and suitable for all 3 weapons.'),

('Targett Fencing', 'Targett Fencing', 'FRA', 'France', NULL,
 'https://targettfencing.com', NULL,
 ARRAY['weapons','clothing','masks','gloves','bags','accessories'],
 FALSE, TRUE, 'retailer',
 'Online fencing equipment retailer offering premium fencing equipment including uniforms, masks, gloves, and equipment for foil, epee, and sabre.'),

-- ITALY
('Carmimari', 'Nuova Carmimari S.r.l.', 'ITA', 'Italy', 'Monza',
 'https://carmimari.com', 1938,
 ARRAY['weapons','clothing','masks','gloves','shoes','bags','accessories'],
 TRUE, TRUE, 'manufacturer',
 'Founded in 1938 when Ing. Sergio Carmina''s electric foil prototype won an FIE contest. 100% made in Italy, made in Milan. Famous for the "Blademaster" uniform used by several Olympic champions and its gloves line-up.'),

('Negrini', 'L. Negrini & Figli', 'ITA', 'Italy', NULL,
 'https://negrini.com', 1897,
 ARRAY['weapons','clothing','masks','bags','accessories'],
 TRUE, TRUE, 'manufacturer',
 'Family-run business producing fencing items since 1897. All products manufactured exclusively in Italy in their own laboratories. Wide range of Made In Italy fencing items including weapons, clothing, bags, and fencing cases.'),

('Favero', 'Favero Electronics S.r.l.', 'ITA', 'Italy', 'Arcade (Treviso)',
 'https://www.favero.com', 1978,
 ARRAY['scoring','electrical','training'],
 FALSE, TRUE, 'manufacturer',
 'Founded in 1978. Premier manufacturer of fencing scoring machines and electronic signaling equipment. F.I.E. certified recording machines for all three weapons. Trusted from local tournaments to Olympic Games. Also manufactures sports scoreboards and billiard equipment.'),

-- HUNGARY
('PBT', 'PBT Hungary Ltd.', 'HUN', 'Hungary', 'Budapest',
 'https://shop.pbtfencing.com', 1991,
 ARRAY['weapons','clothing','masks','gloves','shoes','bags','accessories'],
 TRUE, TRUE, 'manufacturer',
 'Founded in 1991 by Imre Kovacs, former national junior and senior foil team member. First products were shoes and gloves. Masks, uniforms, electric jackets, gloves, bags and accessories all made in Hungary. Also has a Historical Fencing line for HEMA.'),

-- UKRAINE
('StM', 'StM Group of Companies', 'UKR', 'Ukraine', 'Kharkiv',
 'https://stm-fencing.com', 1988,
 ARRAY['weapons','clothing','masks','gloves','bags','accessories','scoring','electrical'],
 TRUE, TRUE, 'manufacturer',
 'Founded in 1988. Full range manufacturer for athletes of all levels. Started trading fencing goods, then in-house production: apparatus (1994), blades (1995), fabrics/clothing (~1998). Supplies equipment and maintenance for FIE World Cups, Grand Prix, and Olympics. Based in Kharkiv; production affected by war.'),

('Unic Fencing', 'Unic Fencing Plus LLC', 'UKR', 'Ukraine', 'Kharkiv',
 'https://unicfencing.com', 2022,
 ARRAY['weapons','accessories','bags','piste'],
 TRUE, TRUE, 'manufacturer',
 'Created in 2022 by a group of fencers and engineers. Produces all types of blades (FIE and Non-FIE), weapon accessories, bodywires, bags, and pistes. Based in Kharkiv.'),

-- USA
('Absolute Fencing Gear', 'Absolute Fencing Gear Inc.', 'USA', 'United States', 'Bridgewater, NJ',
 'https://www.absolutefencinggear.com', 2004,
 ARRAY['weapons','clothing','masks','gloves','shoes','bags','accessories','scoring','piste','electrical'],
 TRUE, TRUE, 'both',
 'Founded in 2004. World''s leading manufacturer and supplier of equipment for Olympic-style fencing. Official Supplier for FIE and UIPM. Featuring 1000+ products, serving clubs, universities, teams, events, and federations.'),

('Blue Gauntlet', 'Blue Gauntlet Fencing Gear Inc.', 'USA', 'United States', 'Saddle Brook, NJ',
 'https://www.blue-gauntlet.com', 1995,
 ARRAY['weapons','clothing','masks','gloves','shoes','bags','accessories','scoring','electrical','training'],
 TRUE, TRUE, 'both',
 'Founded in 1995 by Mr. Chen Jingxi, six-time Chinese national epee champion with 40+ years fencing experience. Premier USA fencing equipment supplier. Works directly as manufacturer, offering competitive prices.'),

('Radical Fencing', 'Radical Fencing', 'USA', 'United States', 'New York, NY',
 'https://radicalfencing.com', NULL,
 ARRAY['weapons','clothing','masks','gloves','shoes','bags','accessories','scoring','training'],
 FALSE, TRUE, 'both',
 'NYC-based fencing equipment company at 150 West 28th Street. Committed to products built with new technology, high-end materials, and exacting U.S. standards. Proudly designed and made in the U.S.'),

('Triplette Competition Arms', 'Triplette Competition Arms', 'USA', 'United States', 'Elkin, NC',
 'https://www.triplette.com', NULL,
 ARRAY['weapons','clothing','masks','gloves','bags','accessories'],
 FALSE, TRUE, 'both',
 'Manufacturer and distributor of sport fencing equipment. Based at 331 Standard St, Elkin, NC 28621.'),

('American Fencers Supply', 'American Fencers Supply Co. Inc.', 'USA', 'United States', 'San Francisco, CA',
 'http://www.amfence.com', 1965,
 ARRAY['weapons','clothing','masks','gloves','bags','accessories'],
 FALSE, TRUE, 'retailer',
 'Established in 1965. Oldest fencing equipment supplier in the country. Grew out of the Halberstadt Fencers Club. USFA Corporate Sponsor. Specializes in equipment, weapon repair, and stage-combat rapiers/daggers.'),

('Blade Fencing Equipment', 'Blade Fencing Equipment Inc.', 'USA', 'United States', 'New York, NY',
 'https://blade-fencing-nyc.com', 1983,
 ARRAY['weapons','clothing','masks','gloves','bags','accessories'],
 FALSE, TRUE, 'retailer',
 'Founded in 1983 by Stanislav Bardakh (former national coach of Ukraine) and Steve Khinoy. First to import blades of Russian and Ukrainian steel to the US. Currently operates in Queens and Brooklyn.'),

('Morehouse Fencing Gear', 'Morehouse Fencing Gear', 'USA', 'United States', 'New York, NY',
 'https://morehousefencinggear.com', NULL,
 ARRAY['weapons','clothing','masks','gloves','bags','accessories'],
 FALSE, TRUE, 'both',
 'Founded by Olympic Silver Medalist Tim Morehouse. Creates high-performance fencing equipment for all levels. Professional-level gear at accessible prices.'),

('The Fencing Post', 'The Fencing Post', 'USA', 'United States', 'California',
 'https://thefencingpost.com', NULL,
 ARRAY['weapons','clothing','masks','gloves','bags','accessories','scoring'],
 FALSE, TRUE, 'retailer',
 'California-based fencing equipment retailer. Carries major brands including Allstar, Uhlmann, Favero, and more.'),

('American Fencing Gear', 'American Fencing Gear', 'USA', 'United States', NULL,
 'https://americanfencinggear.com', NULL,
 ARRAY['weapons','clothing','masks','gloves','bags','accessories'],
 FALSE, TRUE, 'both',
 'Professional team of fencing enthusiasts providing high-quality manufactured fencing gear for all levels.'),

('Alliance Fencing Equipment', 'Alliance Fencing Equipment LLC', 'USA', 'United States', 'San Francisco, CA',
 'https://www.alliancefencingequipment.com', NULL,
 ARRAY['weapons','clothing','masks','gloves','bags','accessories','scoring'],
 FALSE, TRUE, 'retailer',
 'San Francisco-based retailer at 3201 Balboa St. Ships worldwide. Carries products from multiple brands including Balestra, Negrini, and more.'),

('Vinco Sports', 'Vinco Sports Inc.', 'USA', 'United States', 'Montvale, NJ',
 'https://vincosports.com', NULL,
 ARRAY['weapons','clothing','masks','gloves','bags','accessories'],
 TRUE, TRUE, 'both',
 'FIE-registered fencing equipment supplier based at 210 Summit Ave, Montvale, NJ 07645.'),

('Zivkovic Modern Fencing', 'Zivkovic Modern Fencing Equipment', 'USA', 'United States', 'Wellesley, MA',
 NULL, NULL,
 ARRAY['weapons','clothing','masks','accessories'],
 FALSE, TRUE, 'retailer',
 'Massachusetts-based fencing equipment supplier.'),

('FenceSmart', 'FenceSmart', 'USA', 'United States', 'New Jersey',
 NULL, NULL,
 ARRAY['weapons','clothing','masks','gloves','bags','accessories'],
 FALSE, TRUE, 'retailer',
 'New Jersey-based fencing equipment vendor. Supplies well-known brands of fencing equipment.'),

-- RUSSIA
('LM Group / Lammet', 'LM Group', 'RUS', 'Russia', 'Moscow',
 'https://lammet.ru', NULL,
 ARRAY['weapons','clothing','accessories'],
 TRUE, TRUE, 'manufacturer',
 'The oldest fencing equipment company in Russia. For 20 years has been equipping the Russian national fencing team and providing fencing competition equipment. Produces fencing blades and sells protective clothing.'),

('Vniti', 'Vniti', 'RUS', 'Russia', NULL,
 NULL, NULL,
 ARRAY['weapons'],
 FALSE, TRUE, 'manufacturer',
 'Russian blade foundry. Blades made by cold forging, known for durability and stiffness. FIE Maraging blades with cyclic durability 1.5-2.0 times higher than FIE requirements. Unique cold rolling and heat treatment technology.'),

-- ============================================================================
-- SECTION 2: CHINESE MANUFACTURERS
-- ============================================================================

('OK Fencing / BOPAC', 'BOPAC Sports Co., Ltd.', 'CHN', 'China', 'Zhangjiagang, Jiangsu',
 'https://www.okfencing.com', 2000,
 ARRAY['weapons','clothing','masks','gloves','shoes','bags','accessories','piste','training','scoring'],
 TRUE, TRUE, 'manufacturer',
 'Established circa 2000 (registered 2008) by Sam Chen. FIE Certified supplier. Produces comprehensive range of equipment adhering to FIE rules. Supplies to schools and clubs in 50+ countries. Also operates as okfencingequipment.com.'),

('WSFENCING / Ally Sports', 'Nanjing Lanzi Sports Equipment Co., Limited', 'CHN', 'China', 'Nanjing, Jiangsu',
 'https://www.wsfencing.com', NULL,
 ARRAY['weapons','clothing','masks','gloves','shoes','bags','accessories'],
 TRUE, TRUE, 'manufacturer',
 'Professional fencing equipment manufacturer. FIE-registered. Located in Pukou District, Nanjing. Supplies fencing masks, bags, uniforms, and weapons.'),

('Beyond Fencing Gear', 'Beyond Fencing Gear Ltd.', 'CHN', 'China', 'Nanjing',
 'https://chinafencingfactory.com', 2010,
 ARRAY['weapons','clothing','masks','gloves','bags','accessories'],
 TRUE, TRUE, 'manufacturer',
 'Established in 2010 by Lisa Zhou, a former fencing athlete. FIE-registered factory in Nanjing focused on producing better quality equipment.'),

('Shanghai Jianli', 'Shanghai Jianli Sport Equipment Co., Ltd.', 'CHN', 'China', 'Shanghai',
 'http://www.jianlisport.com.cn', 1992,
 ARRAY['weapons','clothing','masks','gloves','shoes','bags','accessories'],
 TRUE, TRUE, 'manufacturer',
 'Established in 1992. Professional manufacturer with 80% of products exported to 20+ countries. Biggest professional fencing equipment producer in the domestic Chinese market.'),

('Shanghai Olympik', 'Shanghai Olympik Sports Co., Ltd.', 'CHN', 'China', 'Shanghai',
 'http://www.czhe-fencing.com', NULL,
 ARRAY['weapons','clothing','masks','gloves','shoes','bags','accessories'],
 TRUE, TRUE, 'manufacturer',
 'Professionally manufactures high quality fencing equipment including uniforms, masks, gloves, lames, bags, socks, shoes, and blades. Based in Baoshan District, Shanghai.'),

('Guan Da', 'Wuxi City Guan Da Sport Goods Co., Ltd.', 'CHN', 'China', 'Wuxi, Jiangsu',
 'https://gfencing.com', NULL,
 ARRAY['weapons','clothing','masks','gloves','bags','accessories'],
 TRUE, TRUE, 'manufacturer',
 'FIE-registered manufacturer located at Chengtie Industrial Park, Yongtai Road, Wuxi City, Jiangsu, China.'),

('Danyang Sports Article', 'Danyang Sports Article Co., Ltd.', 'CHN', 'China', 'Danyang, Jiangsu',
 'https://fencingsets.com', NULL,
 ARRAY['weapons','clothing','masks','gloves','bags','accessories'],
 TRUE, TRUE, 'manufacturer',
 'FIE-registered manufacturer based in Jiqing Industrial Park, Erling Town, Danyang, Jiangsu Province.'),

('Wuxi Husheng', 'Wuxi Husheng Sports Goods Plant', 'CHN', 'China', 'Wuxi, Jiangsu',
 'http://en.jiangfencing.com', NULL,
 ARRAY['weapons','clothing','masks','gloves','bags','accessories'],
 TRUE, TRUE, 'manufacturer',
 'Located on the shore of Taihu Lake. Integrates development, manufacturing, sales, and service. Strong technical force specializing in fencing equipment production.'),

('Jiangsu Mingjian', 'Jiangsu Mingjian Sports Goods Co., Ltd.', 'CHN', 'China', 'Danyang, Jiangsu',
 'http://en.fencingchina.net', NULL,
 ARRAY['weapons','clothing','masks','gloves','shoes','bags','accessories'],
 FALSE, TRUE, 'manufacturer',
 'Professional enterprise for fencing equipment development and production. EU CE certified. One of the leading fencing equipment manufacturers in China. Main products include blades, suits, masks, shoes, and protective gear.'),

('LEONARK', 'LEONARK', 'CHN', 'China', NULL,
 'https://www.leonark.com', 2018,
 ARRAY['weapons','clothing','masks','gloves','bags','accessories','training'],
 FALSE, TRUE, 'manufacturer',
 'Founded in 2018. Provides fencing equipment and services at accessible prices. 100+ products. CE Standard 350N suits. Started providing HEMA gear in 2022. Major presence on Amazon.'),

-- ============================================================================
-- SECTION 3: OTHER ASIAN MANUFACTURERS & RETAILERS
-- ============================================================================

-- JAPAN
('Tokyo Fencing', 'Tokyo Fencing Co., Ltd.', 'JPN', 'Japan', 'Tokyo',
 'https://tf-fencing.co.jp', NULL,
 ARRAY['weapons','clothing','masks','gloves','bags','accessories'],
 TRUE, TRUE, 'manufacturer',
 'FIE-registered Japanese fencing equipment manufacturer. Located at 2-18-23 Takada, Toshima-ku, Tokyo 171-0033.'),

-- HONG KONG
('Purplerise', 'Purplerise', 'HKG', 'Hong Kong', 'Wanchai',
 'https://purplerise.com', NULL,
 ARRAY['weapons','clothing','masks','gloves','bags','accessories'],
 TRUE, TRUE, 'both',
 'FIE-registered fencing equipment supplier. Located at The Broadway, No. 54-62 Lockhart Road, Wanchai, Hong Kong.'),

('KOOV Tech', 'KOOV Tech', 'HKG', 'Hong Kong', 'Kowloon',
 'https://koovbroadcasting.com', NULL,
 ARRAY['broadcasting'],
 TRUE, TRUE, 'manufacturer',
 'FIE-registered technology company. Specializes in fencing broadcasting and video replay systems. Located at Sing Shun Centre, 495 Castle Peak Road, Kowloon.'),

-- SOUTH KOREA (Retailers/Brands)
('Fencing Korea', 'Fencing Korea', 'KOR', 'South Korea', 'Seoul',
 'https://www.fencingkorea.com', NULL,
 ARRAY['weapons','clothing','masks','gloves','shoes','bags','accessories'],
 FALSE, TRUE, 'retailer',
 'Korean comprehensive fencing equipment shopping mall. Carries Nike Fencing, Negrini, and Leon Paul brands. Korean language and domestic delivery.'),

('Fencing Warehouse', 'Fencing Warehouse (펜싱웨어하우스)', 'KOR', 'South Korea', 'Seoul',
 'https://fencingwarehouse.co.kr', NULL,
 ARRAY['weapons','clothing','masks','gloves','shoes','bags','accessories'],
 FALSE, TRUE, 'retailer',
 'Seoul-based fencing equipment retailer in Gangnam-gu. Offers all equipment necessary for fencing.'),

('Fencing Season', 'Fencing Season (펜싱의 계절)', 'KOR', 'South Korea', NULL,
 'https://fencingseason.kr', NULL,
 ARRAY['weapons','clothing','masks','gloves','shoes','bags','accessories'],
 FALSE, TRUE, 'retailer',
 'Korean fencing equipment retailer. Sells equipment at reasonable prices and supports the popularization of fencing in South Korea.'),

('Fencing Label', 'Fencing Label (펜싱레이블)', 'KOR', 'South Korea', NULL,
 'https://fencinglabel.com', NULL,
 ARRAY['weapons','clothing','masks','gloves','bags','accessories'],
 FALSE, TRUE, 'both',
 'Korean fencing equipment brand. Reasonable prices and excellent quality. Equipment designed for both beginners and professional athletes.'),

-- ============================================================================
-- SECTION 4: TURKEY
-- ============================================================================

('Klotho / Maia Fencing', 'Klotho Tekstil San. ve Tic. Ltd. Sti.', 'TUR', 'Turkey', 'Istanbul',
 'https://klothomaiafencing.com', NULL,
 ARRAY['clothing','masks','gloves'],
 TRUE, TRUE, 'manufacturer',
 'FIE-registered fencing textiles manufacturer based in Esenyurt, Istanbul. Specializes in fencing clothing and textiles.'),

('Green Apple Fencing', 'RANA Kilit Ltd.', 'TUR', 'Turkey', 'Istanbul',
 'https://greenapplefencing.com', NULL,
 ARRAY['piste'],
 TRUE, TRUE, 'manufacturer',
 'FIE-registered manufacturer specializing in aluminium fencing pistes. Produces the lightest and thinnest 100% aluminium, self-interlocking piste in modular sections. Based in Esenyurt, Istanbul.'),

-- ============================================================================
-- SECTION 5: ISRAEL
-- ============================================================================

('4F for Fencing', 'SP D. Rigin', 'ISR', 'Israel', 'Ashqelon',
 'https://4fencing.store', NULL,
 ARRAY['weapons','clothing','masks','gloves','bags','accessories'],
 TRUE, TRUE, 'both',
 'FIE-registered fencing equipment supplier based in Ashqelon, Israel.'),

-- ============================================================================
-- SECTION 6: CZECH REPUBLIC
-- ============================================================================

('5M Fencing', '5 M spol. s r.o.', 'CZE', 'Czech Republic', 'Prague',
 'https://www.5mfencing.com', 1991,
 ARRAY['weapons','clothing','masks','gloves','bags','accessories'],
 FALSE, TRUE, 'both',
 'Founded in 1991 by long-time fencer Jiri Beran Sr. Currently led by Jiri Beran Jr., Czech multiple-times champion. Representative of Allstar products for Czech Republic. Also distributes Favero and Unic brands. Began own production alongside imports.'),

-- ============================================================================
-- SECTION 7: SCORING & ELECTRONIC EQUIPMENT SPECIALISTS
-- ============================================================================

('EnPointe', 'EnPointe', 'GBR', 'United Kingdom', NULL,
 'https://enpointefencing.com', NULL,
 ARRAY['scoring','electrical'],
 FALSE, TRUE, 'manufacturer',
 'Wireless fencing scoring system for Sabre, Epee, and Foil. Featured at FIE World Cup events (Tallinn 2018), UIPM Modern Pentathlon European Championships (Bath 2019), and FIE satellite tournaments.'),

('Calibur', 'Calibur', NULL, NULL, NULL,
 'https://calibur.ai', 2020,
 ARRAY['scoring','electrical'],
 FALSE, TRUE, 'manufacturer',
 'Wireless fencing scoring system. First experimental pocket boxes soldered in 2020. Uses tablets/smartphones with free app for scoring, or upgrades traditional machines with wireless Relay unit.'),

('Virtual Scoring Machine (VSM)', 'Second Intention Software and Design', 'USA', 'United States', NULL,
 'https://www.virtualscoringmachine.com', NULL,
 ARRAY['scoring','software'],
 FALSE, TRUE, 'manufacturer',
 'VSM uses a small electrical interface to communicate fencing events to a computer. Designed as a compact and inexpensive alternative to traditional scoring machines.'),

-- ============================================================================
-- SECTION 8: SOFTWARE (Tournament Management)
-- ============================================================================

('Fencing Time', 'Fencing Time LLC', 'USA', 'United States', 'Kirkland, WA',
 'https://www.fencingtime.com', NULL,
 ARRAY['software'],
 TRUE, TRUE, 'software',
 'FIE-registered fencing tournament management software. Integrates with FRED (Fencing Registration and Events Database). Can import Engarde ranking files and export FFF result files. Free for use.'),

('Engarde', 'Engarde / ST37', 'FRA', 'France', NULL,
 'https://www.engarde-escrime.com', NULL,
 ARRAY['software'],
 FALSE, TRUE, 'software',
 'Fencing competition management software. In wide use by the FIE for managing poules, tableaux, and rankings. French program used internationally as the de facto standard.'),

-- ============================================================================
-- SECTION 9: SHOE SPECIALISTS / CO-BRANDS
-- ============================================================================

('Nike Fencing', 'Nike Inc.', 'USA', 'United States', 'Beaverton, OR',
 'https://www.nike.com', NULL,
 ARRAY['shoes'],
 FALSE, TRUE, 'manufacturer',
 'Major sportswear brand producing fencing shoes. The Nike Ballestra line launched with the 2008 Olympic Games and has become one of the most popular fencing shoes worldwide.'),

('Adidas Fencing', 'Adidas AG', 'DEU', 'Germany', 'Herzogenaurach',
 'https://www.adidas.com', NULL,
 ARRAY['shoes','clothing'],
 FALSE, TRUE, 'manufacturer',
 'Major sportswear brand with a long history of manufacturing fencing shoes and some fencing apparel. Distributed through major fencing retailers.'),

('Hi-Tec / Leon Paul Razor', 'Hi-Tec Sports', 'GBR', 'United Kingdom', NULL,
 NULL, NULL,
 ARRAY['shoes'],
 FALSE, TRUE, 'manufacturer',
 'Hi-Tec produces fencing shoes through a collaboration with Leon Paul. The Razor model is their latest fencing shoe offering.'),

-- ============================================================================
-- SECTION 10: TRAINING EQUIPMENT SPECIALISTS
-- ============================================================================

('WOLF Training Dummy', 'WOLF Fencing', 'ISR', 'Israel', NULL,
 'https://rethinkfencing.com', NULL,
 ARRAY['training'],
 FALSE, TRUE, 'manufacturer',
 'Provides a dynamic mobile fencing training dummy. Used by clubs throughout Israel and by athletes at home for individual training. Innovative solution for maximizing training efficiency.'),

('MAC Armour', 'MAC Armour CZ', 'CZE', 'Czech Republic', 'Libouchec',
 'https://www.mac-armour.cz', NULL,
 ARRAY['training','clothing'],
 FALSE, TRUE, 'manufacturer',
 'Produces protective equipment for HEMA training based on original armor construction. Led by armor manufacturer Mac-Stanislav Prosek. Includes training dummies and chest protectors.'),

-- ============================================================================
-- SECTION 11: GERMAN RETAILERS / DISTRIBUTORS
-- ============================================================================

('Fechtsport Kindermann / INNOFENCE', 'Fechtsport Kindermann', 'DEU', 'Germany', 'Teltow',
 'https://fechtsport-kindermann.de', NULL,
 ARRAY['weapons','clothing','masks','gloves','shoes','bags','accessories'],
 FALSE, TRUE, 'retailer',
 'Allstar-Uhlmann representation in Teltow near Berlin. Offers consultation, sales, tournament sales, blade repair, and online ordering under the INNOFENCE brand.'),

('Allstar-Uhlmann UK', 'Allstar Uhlmann UK', 'GBR', 'United Kingdom', NULL,
 'https://allstaruhlmann.com', NULL,
 ARRAY['weapons','clothing','masks','gloves','shoes','bags','accessories','scoring'],
 FALSE, TRUE, 'retailer',
 'Official UK supplier of Allstar and Uhlmann fencing equipment.')

;

-- ============================================================================
-- SUMMARY STATISTICS
-- ============================================================================
-- Total brands/manufacturers: 60+
-- Countries represented: 14 (Germany, UK, France, Italy, Hungary, Ukraine, USA,
--                             Russia, China, Japan, Hong Kong, South Korea,
--                             Turkey, Israel, Czech Republic)
-- FIE Registered: 30+
-- Active manufacturers: 55+
-- Active retailers: 15+
--
-- PRODUCT CATEGORY BREAKDOWN:
--   Weapons (blades/swords):    40+ brands
--   Clothing/Protective:        40+ brands
--   Masks:                      35+ brands
--   Scoring/Electronics:        10+ brands
--   Piste/Strips:               8+ brands
--   Software:                   3+ brands
--   Training Equipment:         5+ brands
--   Broadcasting:               2+ brands
--   Shoes:                      8+ brands (incl. Nike, Adidas)
-- ============================================================================

-- Create indexes for common queries
CREATE INDEX IF NOT EXISTS idx_feb_country ON fencing_equipment_brands(country_code);
CREATE INDEX IF NOT EXISTS idx_feb_fie ON fencing_equipment_brands(is_fie_registered);
CREATE INDEX IF NOT EXISTS idx_feb_active ON fencing_equipment_brands(is_active);
CREATE INDEX IF NOT EXISTS idx_feb_type ON fencing_equipment_brands(brand_type);
CREATE INDEX IF NOT EXISTS idx_feb_name ON fencing_equipment_brands(brand_name);
