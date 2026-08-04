-- Daily chunks so 1-day compression/retention policies can actually fire.
-- Weekly chunks stay open for 7 days, leaving book_deltas as one giant hot chunk.
SELECT set_chunk_time_interval('book_deltas', INTERVAL '1 day');
SELECT set_chunk_time_interval('ticks', INTERVAL '1 day');
SELECT set_chunk_time_interval('trades', INTERVAL '1 day');

-- Compress any closed chunks older than 1 day (open chunk is skipped safely).
DO $$
DECLARE
    chunk regclass;
BEGIN
    FOR chunk IN
        SELECT show_chunks('book_deltas', older_than => INTERVAL '1 day')
    LOOP
        BEGIN
            PERFORM compress_chunk(chunk);
        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE 'book_deltas compress skipped for %: %', chunk, SQLERRM;
        END;
    END LOOP;

    FOR chunk IN
        SELECT show_chunks('ticks', older_than => INTERVAL '1 day')
    LOOP
        BEGIN
            PERFORM compress_chunk(chunk);
        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE 'ticks compress skipped for %: %', chunk, SQLERRM;
        END;
    END LOOP;

    FOR chunk IN
        SELECT show_chunks('trades', older_than => INTERVAL '1 day')
    LOOP
        BEGIN
            PERFORM compress_chunk(chunk);
        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE 'trades compress skipped for %: %', chunk, SQLERRM;
        END;
    END LOOP;
END $$;

-- Tighten continuous-aggregate refresh window (1h -> 15m) to cut rematerialization ~4x.
SELECT remove_continuous_aggregate_policy('ohlcv_1s', if_exists => TRUE);
SELECT add_continuous_aggregate_policy('ohlcv_1s',
    start_offset => INTERVAL '15 minutes',
    end_offset => INTERVAL '1 second',
    schedule_interval => INTERVAL '1 minute',
    if_not_exists => TRUE);

SELECT remove_continuous_aggregate_policy('market_1s', if_exists => TRUE);
SELECT add_continuous_aggregate_policy('market_1s',
    start_offset => INTERVAL '15 minutes',
    end_offset => INTERVAL '1 second',
    schedule_interval => INTERVAL '1 minute',
    if_not_exists => TRUE);

SELECT remove_continuous_aggregate_policy('underlying_1s', if_exists => TRUE);
SELECT add_continuous_aggregate_policy('underlying_1s',
    start_offset => INTERVAL '15 minutes',
    end_offset => INTERVAL '1 second',
    schedule_interval => INTERVAL '1 minute',
    if_not_exists => TRUE);
