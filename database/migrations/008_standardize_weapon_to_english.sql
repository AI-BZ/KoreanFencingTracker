-- Migration 008: Standardize weapon column values to English codes
-- Before: 플뢰레/플러레, 에페/에뻬, 사브르 (Korean, inconsistent)
-- After: foil, epee, sabre (English, consistent)

-- events.weapon
UPDATE events SET weapon = 'foil' WHERE weapon IN ('플뢰레', '플러레');
UPDATE events SET weapon = 'epee' WHERE weapon IN ('에페', '에뻬');
UPDATE events SET weapon = 'sabre' WHERE weapon = '사브르';

-- player_rankings.weapon (if exists)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'player_rankings') THEN
        UPDATE player_rankings SET weapon = 'foil' WHERE weapon IN ('플뢰레', '플러레');
        UPDATE player_rankings SET weapon = 'epee' WHERE weapon IN ('에페', '에뻬');
        UPDATE player_rankings SET weapon = 'sabre' WHERE weapon = '사브르';
    END IF;
END $$;
