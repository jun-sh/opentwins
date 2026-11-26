option task = {name: "phm-downsample-30s", every: 1m, offset: 10s}

// 30 s joint aggregates for PHM (worker history and fixed baselines) in bucket phm_agg: milliseconds to
// query instead of scanning raw kHz samples, and kept when raw expires. Field names = phm_worker FIELDS.
// The last 3 min are rewritten every run (same timestamps), so late or partial windows are corrected.
// scripts/influx-backfill.sh runs this file with another range for history.
src = (fld, fn, as) => from(bucket: "raw") |> range(start: -3m)
    |> filter(fn: (r) => r._measurement == "telemetry" and r.feature_id =~ /(_joint|^joint[0-9]+)$/ and r._field == fld)
    |> aggregateWindow(every: 30s, fn: fn, createEmpty: false) |> set(key: "_field", value: as)

union(tables: [src(fld: "windingTemperature", fn: mean, as: "windingTemperature"),
    src(fld: "driverTemperature", fn: mean, as: "driverTemperature"), src(fld: "torque", fn: mean, as: "torque"),
    src(fld: "velocity", fn: mean, as: "velocity"), src(fld: "torque", fn: min, as: "torqueMin"),
    src(fld: "torque", fn: max, as: "torqueMax"), src(fld: "faultCode", fn: max, as: "faultCode")])
    |> set(key: "_measurement", value: "telemetry_30s")
    |> keep(columns: ["_time", "_value", "_field", "_measurement", "thing_id", "feature_id"])
    |> to(bucket: "phm_agg")
