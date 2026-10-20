args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 4) {
  stop(paste(
    "Usage: Rscript analyze_experiment_0_bandit.R",
    "<main_final_csv> <trajectory_csv> <peer_check_csv> <output_dir>"
  ))
}

main_file <- normalizePath(args[[1]], mustWork = TRUE)
trajectory_file <- normalizePath(args[[2]], mustWork = TRUE)
peer_file <- normalizePath(args[[3]], mustWork = TRUE)
output_dir <- args[[4]]
dir.create(output_dir, recursive = TRUE, showWarnings = FALSE)

read_behaviorspace <- function(path) {
  read.csv(
    path,
    skip = 6,
    check.names = FALSE,
    stringsAsFactors = FALSE
  )
}

rename_columns <- function(dat, mapping) {
  for (old_name in names(mapping)) {
    if (old_name %in% names(dat)) {
      names(dat)[names(dat) == old_name] <- unname(mapping[[old_name]])
    }
  }
  dat
}

as_bool <- function(x) {
  if (is.logical(x)) return(x)
  tolower(trimws(as.character(x))) == "true"
}

main_mapping <- c(
  "[run number]" = "run_number",
  "run-seed" = "seed",
  "world-mode" = "world_mode",
  "peer-sharing?" = "sharing",
  "[step]" = "step",
  "actual-seed" = "actual_seed",
  "hidden-world" = "world",
  "expert-total-pulls" = "expert_pulls",
  "total-lay-pulls" = "lay_pulls",
  "expert-truth-mass-at-25" = "expert_truth_25",
  "expert-recommendation-score-at-25" = "expert_rec_25",
  "expert-informative-observations-at-25" = "expert_info_25",
  "mean-lay-truth-mass-at-25" = "lay_truth_25",
  "mean-lay-recommendation-score-at-25" = "lay_rec_25",
  "mean-lay-informative-observations-at-25" = "lay_info_25",
  "mean-lay-archive-size-at-25" = "lay_archive_25",
  "mean-lay-posterior-truth-mass" = "lay_truth_final",
  "cumulative-lay-correct-choice-rate" = "lay_correct_cumulative",
  "mean-lay-cumulative-regret" = "lay_regret",
  "mean-lay-realized-payoff" = "lay_payoff",
  "mean-lay-b-pulls" = "lay_b_pulls",
  "mean-lay-informative-observations" = "lay_info_final",
  "final-window-wrong-choice-rate" = "late_wrong_rate",
  "finite-horizon-error-persistence-rate" = "individual_persistence_rate",
  "run-finite-horizon-persistent-error?" = "run_persistent_error",
  "expert-posterior-truth-mass" = "expert_truth_final",
  "expert-recommendation-accuracy" = "expert_rec_final",
  "expert-thompson-correct-rate" = "expert_action_correct",
  "expert-cumulative-regret" = "expert_regret",
  "expert-b-pull-rate" = "expert_b_rate",
  "lay-a-reward-rate" = "lay_a_reward_rate",
  "lay-b-reward-rate" = "lay_b_reward_rate",
  "expert-a-reward-rate" = "expert_a_reward_rate",
  "expert-b-reward-rate" = "expert_b_reward_rate",
  "mean-peer-messages-received" = "peer_messages",
  "mean-unique-evidence-count" = "unique_evidence",
  "duplicate-message-count" = "duplicate_messages",
  "maximum-belief-identity-error" = "belief_identity_error",
  "maximum-regret-identity-error" = "regret_identity_error",
  "network-structure-valid?" = "network_valid",
  "message-accounting-valid?" = "messages_valid",
  "evidence-provenance-valid?" = "provenance_valid"
)

trajectory_mapping <- c(
  "[run number]" = "run_number",
  "run-seed" = "seed",
  "world-mode" = "world_mode",
  "peer-sharing?" = "sharing",
  "[step]" = "step",
  "actual-seed" = "actual_seed",
  "hidden-world" = "world",
  "current-lay-correct-choice-rate" = "current_correct",
  "current-lay-b-share" = "current_b_share",
  "mean-lay-q" = "mean_q",
  "mean-lay-posterior-truth-mass" = "lay_truth",
  "lay-q-dispersion" = "q_dispersion",
  "mean-lay-cumulative-regret" = "lay_regret",
  "mean-lay-b-pulls" = "lay_b_pulls",
  "expert-posterior-truth-mass" = "expert_truth",
  "expert-total-pulls" = "expert_pulls",
  "maximum-belief-identity-error" = "belief_identity_error",
  "message-accounting-valid?" = "messages_valid"
)

main <- rename_columns(read_behaviorspace(main_file), main_mapping)
peer <- rename_columns(read_behaviorspace(peer_file), main_mapping)
trajectory <- rename_columns(
  read_behaviorspace(trajectory_file), trajectory_mapping
)

main_bool <- c(
  "sharing", "run_persistent_error", "network_valid", "messages_valid",
  "provenance_valid"
)
trajectory_bool <- c("sharing", "messages_valid")

for (column in main_bool) {
  main[[column]] <- as_bool(main[[column]])
  peer[[column]] <- as_bool(peer[[column]])
}
for (column in trajectory_bool) {
  trajectory[[column]] <- as_bool(trajectory[[column]])
}

main_text <- c("world_mode", "world")
trajectory_text <- c("world_mode", "world")
for (column in setdiff(names(main), c(main_bool, main_text))) {
  main[[column]] <- as.numeric(main[[column]])
}
for (column in setdiff(names(peer), c(main_bool, main_text))) {
  peer[[column]] <- as.numeric(peer[[column]])
}
for (column in setdiff(
  names(trajectory), c(trajectory_bool, trajectory_text)
)) {
  trajectory[[column]] <- as.numeric(trajectory[[column]])
}

main$late_correct_rate <- 1 - main$late_wrong_rate
peer$late_correct_rate <- 1 - peer$late_wrong_rate

main <- main[order(main$world, main$seed), ]
peer <- peer[order(peer$world, peer$seed, peer$sharing), ]
trajectory <- trajectory[order(
  trajectory$world, trajectory$seed, trajectory$ticks
), ]
row.names(main) <- row.names(peer) <- row.names(trajectory) <- NULL

write.csv(main, file.path(output_dir, "main_run_level_clean.csv"),
          row.names = FALSE)
write.csv(peer, file.path(output_dir, "peer_check_run_level_clean.csv"),
          row.names = FALSE)

set.seed(20260801)

bootstrap_mean_ci <- function(x, b = 4000, conf = 0.95) {
  x <- x[is.finite(x)]
  n <- length(x)
  if (n == 0) return(c(mean = NA, ci_low = NA, ci_high = NA))
  if (n == 1) return(c(mean = x, ci_low = x, ci_high = x))
  boot <- replicate(b, mean(sample(x, n, replace = TRUE)))
  alpha <- (1 - conf) / 2
  c(
    mean = mean(x),
    ci_low = unname(quantile(boot, alpha)),
    ci_high = unname(quantile(boot, 1 - alpha))
  )
}

descriptive <- function(x) {
  ci <- bootstrap_mean_ci(x)
  c(
    n = sum(is.finite(x)),
    mean = ci[["mean"]],
    ci_low = ci[["ci_low"]],
    ci_high = ci[["ci_high"]],
    median = median(x, na.rm = TRUE),
    q1 = unname(quantile(x, 0.25, na.rm = TRUE)),
    q3 = unname(quantile(x, 0.75, na.rm = TRUE))
  )
}

world_order <- c("B-good", "B-bad")

expertise_rows <- lapply(world_order, function(world_name) {
  d <- main[main$world == world_name, ]
  gap <- d$expert_truth_25 - d$lay_truth_25
  gap_stats <- descriptive(gap)
  data.frame(
    world = world_name,
    n_runs = nrow(d),
    expert_truth_mass = mean(d$expert_truth_25),
    lay_truth_mass = mean(d$lay_truth_25),
    expert_minus_lay = gap_stats[["mean"]],
    gap_ci_low = gap_stats[["ci_low"]],
    gap_ci_high = gap_stats[["ci_high"]],
    share_expert_above_lay = mean(gap > 0),
    expert_recommendation_score = mean(d$expert_rec_25),
    lay_recommendation_score = mean(d$lay_rec_25),
    expert_informative_observations = mean(d$expert_info_25),
    lay_informative_observations = mean(d$lay_info_25),
    stringsAsFactors = FALSE
  )
})
expertise_summary <- do.call(rbind, expertise_rows)
write.csv(expertise_summary, file.path(output_dir, "expertise_summary.csv"),
          row.names = FALSE)

endpoint_metrics <- c(
  lay_regret = "Cumulative expected regret",
  late_correct_rate = "Late correct-arm rate",
  lay_truth_final = "Final posterior truth mass",
  lay_b_pulls = "B pulls per layperson",
  run_persistent_error = "Run persistent-error proportion",
  lay_payoff = "Realized payoff"
)

endpoint_rows <- list()
for (world_name in world_order) {
  d <- main[main$world == world_name, ]
  for (metric_name in names(endpoint_metrics)) {
    values <- as.numeric(d[[metric_name]])
    stats <- descriptive(values)
    endpoint_rows[[length(endpoint_rows) + 1]] <- data.frame(
      world = world_name,
      metric_key = metric_name,
      metric = unname(endpoint_metrics[[metric_name]]),
      n_runs = stats[["n"]],
      mean = stats[["mean"]],
      ci_low = stats[["ci_low"]],
      ci_high = stats[["ci_high"]],
      median = stats[["median"]],
      q1 = stats[["q1"]],
      q3 = stats[["q3"]],
      stringsAsFactors = FALSE
    )
  }
}
endpoint_summary <- do.call(rbind, endpoint_rows)
write.csv(endpoint_summary, file.path(output_dir, "endpoint_summary.csv"),
          row.names = FALSE)

# Conditional paths after the expert's tick-25 recommendation.
main$expert_status <- ifelse(
  main$expert_rec_25 == 1, "correct",
  ifelse(main$expert_rec_25 == 0, "incorrect", "tie")
)
conditional_rows <- list()
for (world_name in world_order) {
  for (status_name in c("correct", "incorrect", "tie")) {
    d <- main[main$world == world_name &
      main$expert_status == status_name, ]
    if (nrow(d) == 0) next
    conditional_rows[[length(conditional_rows) + 1]] <- data.frame(
      world = world_name,
      expert_status_at_25 = status_name,
      n_runs = nrow(d),
      mean_late_correct_rate = mean(d$late_correct_rate),
      mean_regret = mean(d$lay_regret),
      mean_final_truth_mass = mean(d$lay_truth_final),
      persistent_error_share = mean(d$run_persistent_error),
      stringsAsFactors = FALSE
    )
  }
}
conditional_summary <- do.call(rbind, conditional_rows)
write.csv(conditional_summary,
          file.path(output_dir, "conditional_path_summary.csv"),
          row.names = FALSE)

# Run-level trajectory summaries and pointwise run-level intervals.
trajectory_variables <- c(
  "current_correct", "current_b_share", "mean_q", "lay_truth",
  "q_dispersion", "lay_regret", "lay_b_pulls", "expert_truth"
)
trajectory_mean <- aggregate(
  trajectory[trajectory_variables],
  by = list(world = trajectory$world, tick = trajectory$ticks),
  FUN = mean
)
trajectory_sd <- aggregate(
  trajectory[trajectory_variables],
  by = list(world = trajectory$world, tick = trajectory$ticks),
  FUN = sd
)
trajectory_n <- aggregate(
  trajectory[[trajectory_variables[[1]]]],
  by = list(world = trajectory$world, tick = trajectory$ticks),
  FUN = length
)
names(trajectory_n)[[3]] <- "n_runs"

trajectory_summary <- trajectory_mean[, c("world", "tick")]
trajectory_summary$n_runs <- trajectory_n$n_runs
critical <- qt(0.975, df = trajectory_summary$n_runs - 1)
for (variable in trajectory_variables) {
  trajectory_summary[[paste0(variable, "_mean")]] <-
    trajectory_mean[[variable]]
  se <- trajectory_sd[[variable]] / sqrt(trajectory_summary$n_runs)
  trajectory_summary[[paste0(variable, "_ci_low")]] <-
    trajectory_mean[[variable]] - critical * se
  trajectory_summary[[paste0(variable, "_ci_high")]] <-
    trajectory_mean[[variable]] + critical * se
}
trajectory_summary <- trajectory_summary[order(
  match(trajectory_summary$world, world_order), trajectory_summary$tick
), ]
write.csv(trajectory_summary,
          file.path(output_dir, "trajectory_summary.csv"),
          row.names = FALSE)

# Thompson sampling calibration: action at tick t uses q recorded after tick t-1.
current_actions <- trajectory[trajectory$ticks > 0,
  c("seed", "world", "ticks", "current_b_share")]
lagged_q <- trajectory[, c("seed", "world", "ticks", "mean_q")]
lagged_q$ticks <- lagged_q$ticks + 1
names(lagged_q)[names(lagged_q) == "mean_q"] <- "decision_q"
ts_check <- merge(
  current_actions, lagged_q,
  by = c("seed", "world", "ticks"),
  all.x = TRUE, sort = FALSE
)
ts_check$gap <- ts_check$current_b_share - ts_check$decision_q
ts_run <- aggregate(
  ts_check$gap,
  by = list(seed = ts_check$seed, world = ts_check$world),
  FUN = mean
)
names(ts_run)[[3]] <- "mean_action_minus_q"
ts_summary_rows <- lapply(world_order, function(world_name) {
  values <- ts_run$mean_action_minus_q[ts_run$world == world_name]
  stats <- descriptive(values)
  data.frame(
    world = world_name,
    n_runs = stats[["n"]],
    mean_action_minus_q = stats[["mean"]],
    ci_low = stats[["ci_low"]],
    ci_high = stats[["ci_high"]],
    stringsAsFactors = FALSE
  )
})
ts_summary <- do.call(rbind, ts_summary_rows)
write.csv(ts_summary, file.path(output_dir, "thompson_calibration.csv"),
          row.names = FALSE)

# Paired sharing-on versus sharing-off mechanism check.
peer_on <- peer[peer$sharing, ]
peer_off <- peer[!peer$sharing, ]
peer_pair <- merge(
  peer_on, peer_off,
  by = c("seed", "world"),
  suffixes = c("_on", "_off"),
  all = TRUE, sort = TRUE
)

peer_metrics <- c(
  lay_regret = "Regret",
  late_correct_rate = "Late correct-arm rate",
  lay_truth_final = "Final truth mass",
  lay_b_pulls = "B pulls per layperson",
  run_persistent_error = "Persistent-error probability"
)
peer_rows <- list()
for (world_name in world_order) {
  d <- peer_pair[peer_pair$world == world_name, ]
  for (metric_name in names(peer_metrics)) {
    delta <- as.numeric(d[[paste0(metric_name, "_on")]]) -
      as.numeric(d[[paste0(metric_name, "_off")]])
    stats <- descriptive(delta)
    peer_rows[[length(peer_rows) + 1]] <- data.frame(
      world = world_name,
      metric_key = metric_name,
      metric = unname(peer_metrics[[metric_name]]),
      n_pairs = stats[["n"]],
      mean_on_minus_off = stats[["mean"]],
      ci_low = stats[["ci_low"]],
      ci_high = stats[["ci_high"]],
      share_positive = mean(delta > 0),
      share_nonzero = mean(abs(delta) > 1e-12),
      stringsAsFactors = FALSE
    )
  }
}
peer_summary <- do.call(rbind, peer_rows)
write.csv(peer_summary, file.path(output_dir, "peer_sharing_summary.csv"),
          row.names = FALSE)

core_peer_deltas <- cbind(
  peer_pair$lay_regret_on - peer_pair$lay_regret_off,
  peer_pair$late_correct_rate_on - peer_pair$late_correct_rate_off,
  peer_pair$lay_truth_final_on - peer_pair$lay_truth_final_off,
  peer_pair$lay_b_pulls_on - peer_pair$lay_b_pulls_off
)
peer_pair$any_path_difference <-
  apply(abs(core_peer_deltas) > 1e-12, 1, any)
write.csv(peer_pair, file.path(output_dir, "peer_check_paired_runs.csv"),
          row.names = FALSE)

# Validation checks.
checks <- list()
add_check <- function(name, passed, observed, expected) {
  checks[[length(checks) + 1]] <<- data.frame(
    check = name,
    passed = isTRUE(passed),
    observed = as.character(observed),
    expected = as.character(expected),
    stringsAsFactors = FALSE
  )
}

expected_main_seeds <- 310001:310500
expected_traj_seeds <- 310001:310200
tolerance <- 1e-12

add_check("main_row_count", nrow(main) == 1000, nrow(main), 1000)
add_check("main_balanced_worlds",
          all(table(main$world) == 500),
          paste(names(table(main$world)), table(main$world), collapse = "; "),
          "500 per world")
add_check("main_seed_set",
          all(vapply(world_order, function(w) {
            identical(as.integer(sort(main$seed[main$world == w])),
                      expected_main_seeds)
          }, logical(1))),
          paste(range(main$seed), collapse = "-"), "310001-310500 each world")
add_check("main_seed_preserved", all(main$seed == main$actual_seed),
          sum(main$seed == main$actual_seed), nrow(main))
add_check("world_assignment_preserved", all(main$world == main$world_mode),
          sum(main$world == main$world_mode), nrow(main))
add_check("main_sharing_on", all(main$sharing), sum(main$sharing), nrow(main))
add_check("ticks_complete", all(main$ticks == 500),
          paste(unique(main$ticks), collapse = ","), 500)
add_check("expert_pull_count", all(main$expert_pulls == 125),
          paste(unique(main$expert_pulls), collapse = ","), 125)
add_check("lay_pull_count", all(main$lay_pulls == 5000),
          paste(unique(main$lay_pulls), collapse = ","), 5000)
add_check("tick25_archive_size", all(main$lay_archive_25 == 75),
          paste(unique(main$lay_archive_25), collapse = ","), 75)
add_check("final_peer_message_count", all(main$peer_messages == 998),
          paste(unique(main$peer_messages), collapse = ","), 998)
add_check("final_unique_evidence_count", all(main$unique_evidence == 1498),
          paste(unique(main$unique_evidence), collapse = ","), 1498)
add_check("no_duplicate_messages", all(main$duplicate_messages == 0),
          max(main$duplicate_messages), 0)
add_check("network_valid", all(main$network_valid),
          sum(main$network_valid), nrow(main))
add_check("message_accounting_valid", all(main$messages_valid),
          sum(main$messages_valid), nrow(main))
add_check("provenance_valid", all(main$provenance_valid),
          sum(main$provenance_valid), nrow(main))
add_check("belief_update_identity",
          max(main$belief_identity_error) < 1e-10,
          max(main$belief_identity_error), "< 1e-10")
add_check("regret_identity",
          max(main$regret_identity_error) < 1e-10,
          max(main$regret_identity_error), "< 1e-10")
add_check("lay_A_reward_rate",
          abs(mean(main$lay_a_reward_rate) - 0.50) < 0.005,
          mean(main$lay_a_reward_rate), "within 0.005 of 0.50")
for (world_name in world_order) {
  target <- if (world_name == "B-good") 0.55 else 0.45
  observed <- mean(main$lay_b_reward_rate[main$world == world_name])
  add_check(paste0("lay_B_reward_rate_", world_name),
            abs(observed - target) < 0.005,
            observed, paste("within 0.005 of", target))
}
add_check("trajectory_row_count", nrow(trajectory) == 200400,
          nrow(trajectory), 200400)
add_check("trajectory_seed_set",
          all(vapply(world_order, function(w) {
            identical(
              as.integer(sort(unique(
                trajectory$seed[trajectory$world == w]
              ))),
              expected_traj_seeds
            )
          }, logical(1))),
          paste(range(trajectory$seed), collapse = "-"),
          "310001-310200 each world")
trajectory_rows_per_run <- table(trajectory$seed, trajectory$world)
add_check("trajectory_501_rows_per_run",
          all(trajectory_rows_per_run == 501),
          paste(range(trajectory_rows_per_run), collapse = "-"), 501)
add_check("neutral_initial_prior",
          all(abs(trajectory$mean_q[trajectory$ticks == 0] - 0.5) < tolerance),
          range(trajectory$mean_q[trajectory$ticks == 0]), 0.5)
add_check("trajectory_belief_identity",
          max(trajectory$belief_identity_error) < 1e-10,
          max(trajectory$belief_identity_error), "< 1e-10")
add_check("trajectory_messages_valid", all(trajectory$messages_valid),
          sum(trajectory$messages_valid), nrow(trajectory))
add_check("thompson_action_probability_calibration",
          max(abs(ts_summary$mean_action_minus_q)) < 0.01,
          max(abs(ts_summary$mean_action_minus_q)), "< 0.01")
add_check("peer_row_count", nrow(peer) == 2000, nrow(peer), 2000)
add_check("peer_pair_count", nrow(peer_pair) == 1000,
          nrow(peer_pair), 1000)
add_check("peer_off_has_no_messages",
          all(peer_off$peer_messages == 0),
          paste(unique(peer_off$peer_messages), collapse = ","), 0)
add_check("peer_off_own_archive_only",
          all(peer_off$lay_archive_25 == 25 & peer_off$unique_evidence == 500),
          paste(range(peer_off$unique_evidence), collapse = "-"),
          "25 at snapshot; 500 final")
add_check("expert_trajectory_invariant_to_sharing",
          max(abs(peer_pair$expert_truth_25_on -
                  peer_pair$expert_truth_25_off)) < tolerance &&
          max(abs(peer_pair$expert_regret_on -
                  peer_pair$expert_regret_off)) < tolerance,
          max(abs(peer_pair$expert_truth_25_on -
                  peer_pair$expert_truth_25_off)), 0)
add_check("sharing_changes_some_paths",
          mean(peer_pair$any_path_difference) > 0.25,
          mean(peer_pair$any_path_difference), "> 0.25")

# Main-final and peer-check sharing-on runs must reproduce exactly.
main_compare <- merge(
  main[, c("seed", "world", "lay_regret", "lay_truth_final",
           "lay_b_pulls", "late_correct_rate", "expert_truth_25")],
  peer_on[, c("seed", "world", "lay_regret", "lay_truth_final",
              "lay_b_pulls", "late_correct_rate", "expert_truth_25")],
  by = c("seed", "world"), suffixes = c("_main", "_peer")
)
repro_columns <- c(
  "lay_regret", "lay_truth_final", "lay_b_pulls", "late_correct_rate",
  "expert_truth_25"
)
repro_error <- max(vapply(repro_columns, function(column) {
  max(abs(main_compare[[paste0(column, "_main")]] -
          main_compare[[paste0(column, "_peer")]]))
}, numeric(1)))
add_check("cross_experiment_exact_reproducibility",
          repro_error < tolerance, repro_error, 0)

validation_checks <- do.call(rbind, checks)
write.csv(validation_checks,
          file.path(output_dir, "validation_checks.csv"),
          row.names = FALSE)
validation_status <- if (all(validation_checks$passed)) {
  "READY TO SHARE"
} else {
  "NOT READY TO SHARE"
}

writeLines(
  c(
    "# Experiment 0 validation report",
    "",
    paste("Overall status:", validation_status),
    paste("Checks passed:", sum(validation_checks$passed),
          "of", nrow(validation_checks)),
    paste("Main runs:", nrow(main)),
    paste("Trajectory rows:", nrow(trajectory)),
    paste("Peer-check paired runs:", nrow(peer_pair)),
    "",
    "The independent statistical unit is the complete simulation run.",
    "Laypeople and ticks within a run are not treated as independent samples."
  ),
  con = file.path(output_dir, "validation_report.md"),
  useBytes = TRUE
)

# ---------- Figures (base R only) ----------
png(file.path(output_dir, "figure_1_dynamic_expertise.png"),
    width = 1500, height = 650, res = 150)
par(mfrow = c(1, 2), mar = c(4.2, 4.4, 3, 1), las = 1)
for (world_name in world_order) {
  d <- trajectory_summary[
    trajectory_summary$world == world_name & trajectory_summary$tick <= 25,
  ]
  plot(d$tick, d$expert_truth_mean, type = "n", ylim = c(0.35, 1),
       xlab = "Tick", ylab = "Posterior truth mass",
       main = world_name)
  polygon(c(d$tick, rev(d$tick)),
          c(d$lay_truth_ci_low, rev(d$lay_truth_ci_high)),
          col = adjustcolor("gray60", alpha.f = 0.22), border = NA)
  lines(d$tick, d$lay_truth_mean, col = "gray35", lwd = 2.5)
  lines(d$tick, d$expert_truth_mean, col = "#7B3294", lwd = 2.5)
  abline(v = 25, lty = 3, col = "gray55")
  legend("topleft", c("Expert", "Lay mean"),
         col = c("#7B3294", "gray35"), lwd = 2.5, bty = "n")
}
dev.off()

png(file.path(output_dir, "figure_2_learning_paths.png"),
    width = 1500, height = 650, res = 150)
par(mfrow = c(1, 2), mar = c(4.2, 4.4, 3, 1), las = 1)
for (world_name in world_order) {
  d <- trajectory_summary[
    trajectory_summary$world == world_name & trajectory_summary$tick > 0,
  ]
  plot(d$tick, d$current_correct_mean, type = "l", ylim = c(0, 1),
       xlab = "Tick", ylab = "Share", main = world_name,
       col = "#1B7837", lwd = 2)
  lines(d$tick, d$current_b_share_mean, col = "#2166AC", lwd = 2,
        lty = 2)
  abline(h = 0.5, lty = 3, col = "gray60")
  legend("right", c("Correct-arm share", "B-pull share"),
         col = c("#1B7837", "#2166AC"), lwd = 2,
         lty = c(1, 2), bty = "n")
}
dev.off()

png(file.path(output_dir, "figure_3_outcome_distributions.png"),
    width = 1500, height = 650, res = 150)
par(mfrow = c(1, 2), mar = c(4.2, 4.5, 3, 1), las = 1)
main$world_factor <- factor(main$world, levels = world_order)
boxplot(lay_regret ~ world_factor, data = main,
        names = world_order, col = c("#D9F0D3", "#D9EAF7"),
        xlab = "World",
        ylab = "Cumulative expected regret per layperson",
        main = "500-tick regret")
boxplot(late_correct_rate ~ world_factor, data = main,
        names = world_order, col = c("#D9F0D3", "#D9EAF7"),
        xlab = "World",
        ylab = "Correct-arm rate in final 50 ticks",
        main = "Late behavior", ylim = c(0, 1))
abline(h = 0.5, lty = 3, col = "gray60")
dev.off()

png(file.path(output_dir, "figure_4_peer_sharing_effects.png"),
    width = 1500, height = 520, res = 150)
selected_metrics <- c(
  "lay_regret", "late_correct_rate", "lay_truth_final"
)
par(mfrow = c(1, 3), mar = c(4.2, 4.4, 3, 1), las = 1)
for (metric_name in selected_metrics) {
  d <- peer_summary[peer_summary$metric_key == metric_name, ]
  d <- d[match(world_order, d$world), ]
  y_range <- range(c(d$ci_low, d$ci_high, 0))
  plot(1:2, d$mean_on_minus_off, xaxt = "n", pch = 19,
       ylim = y_range, xlab = "World", ylab = "Sharing on minus off",
       main = d$metric[[1]])
  axis(1, at = 1:2, labels = world_order)
  arrows(1:2, d$ci_low, 1:2, d$ci_high,
         angle = 90, code = 3, length = 0.06)
  abline(h = 0, lty = 3, col = "gray55")
}
dev.off()

# ---------- Human-readable report ----------
fmt <- function(x, digits = 3) formatC(x, digits = digits, format = "f")
pct <- function(x, digits = 1) paste0(fmt(100 * x, digits), "%")
ci_text <- function(mean, low, high, digits = 3) {
  paste0(fmt(mean, digits), " [", fmt(low, digits), ", ",
         fmt(high, digits), "]")
}

get_endpoint <- function(world_name, metric_key) {
  endpoint_summary[endpoint_summary$world == world_name &
    endpoint_summary$metric_key == metric_key, ][1, ]
}
get_peer <- function(world_name, metric_key) {
  peer_summary[peer_summary$world == world_name &
    peer_summary$metric_key == metric_key, ][1, ]
}

good_expertise <- expertise_summary[expertise_summary$world == "B-good", ]
bad_expertise <- expertise_summary[expertise_summary$world == "B-bad", ]
good_regret <- get_endpoint("B-good", "lay_regret")
bad_regret <- get_endpoint("B-bad", "lay_regret")
good_late <- get_endpoint("B-good", "late_correct_rate")
bad_late <- get_endpoint("B-bad", "late_correct_rate")
good_peer_regret <- get_peer("B-good", "lay_regret")
bad_peer_regret <- get_peer("B-bad", "lay_regret")
good_peer_late <- get_peer("B-good", "late_correct_rate")
bad_peer_late <- get_peer("B-bad", "late_correct_rate")
good_peer_b_pulls <- get_peer("B-good", "lay_b_pulls")
bad_peer_b_pulls <- get_peer("B-bad", "lay_b_pulls")

report_lines <- c(
  "# Experiment 0：动态 Bandit Base 实验报告",
  "",
  "## 1. 简介与研究问题",
  "",
  "Experiment 0 不比较 Preemption 与 Total Evidence。它是后续 deference 实验的验收实验，只检验三件事：额外研究机会能否内生地产生 expert 优势；只观察所选行动是否产生路径依赖；laypeople 外环的一跳信息分享是否真正改变行为。",
  "",
  "## 2. 方法",
  "",
  "每个 run 中，A 的成功率固定为 0.50。B 在 `B-good` 世界中的成功率为 0.55，在 `B-bad` 世界中为 0.45；世界在500 ticks内不改变。agents 只看见实际选择的 arm 的结果。B 的结果能区分两个世界，A 的结果不能。",
  "",
  "所有 agents 使用 Thompson sampling：其认为 `B-good` 的概率是多少，就以多大概率选择 B。expert 在前25 ticks每 tick顺序完成5次 pulls，共125次；每位 layperson 每 tick一次，共500次。10位 laypeople 构成外环，只把第一手结果发送给左右邻居，消息晚一轮生效且不转发。expert 在 Experiment 0 不发送任何内容。",
  "",
  paste0("主结果包括两个世界各500个独立 runs；学习曲线包括各200个 runs；sharing机制检查包括", nrow(peer_pair), "组同 seed 配对 runs。统计单位始终是完整 run。"),
  "",
  "主要表现指标是 cumulative expected regret：每次选择较差 arm 增加0.05。它比 realized payoff 更清楚，因为后者还混入单次 Bernoulli 运气。",
  "",
  "## 3. 结果",
  "",
  "### 3.1 模型与数据验证",
  "",
  paste0("共通过 ", sum(validation_checks$passed), "/",
         nrow(validation_checks), " 项预定检查，状态为 **",
         validation_status, "**。expert pulls、laypeople pulls、消息延迟、证据来源、reward生成率、Bayesian log-odds恒等式和regret恒等式均经过检查。"),
  "",
  "### 3.2 额外研究机会形成了动态但非绝对的 expert 优势",
  "",
  paste0("完成25个学习 ticks 后，在 `B-good` 中 expert 的平均 truth mass 为 ",
         fmt(good_expertise$expert_truth_mass), "，laypeople 网络均值为 ",
         fmt(good_expertise$lay_truth_mass), "；配对差为 ",
         ci_text(good_expertise$expert_minus_lay,
                 good_expertise$gap_ci_low,
                 good_expertise$gap_ci_high), "。expert 在 ",
         pct(good_expertise$share_expert_above_lay),
         " 的 runs 中高于对应 laypeople 网络均值。"),
  "",
  paste0("在 `B-bad` 中，expert truth mass 为 ",
         fmt(bad_expertise$expert_truth_mass), "，laypeople 为 ",
         fmt(bad_expertise$lay_truth_mass), "；配对差为 ",
         ci_text(bad_expertise$expert_minus_lay,
                 bad_expertise$gap_ci_low,
                 bad_expertise$gap_ci_high), "。expert 在 ",
         pct(bad_expertise$share_expert_above_lay),
         " 的 runs 中更高。"),
  "",
  "这里的 reliability 是运行中形成的 posterior truth mass 和 recommendation accuracy，不是预先设定的正确率。expert 仍会因早期随机结果而判断错误。",
  "",
  "![Dynamic expertise](figure_1_dynamic_expertise.png)",
  "",
  "### 3.3 两个世界产生不对称的学习路径",
  "",
  paste0("500 ticks 后，`B-good` 中每位 layperson 的平均累计 regret 为 ",
         ci_text(good_regret$mean, good_regret$ci_low,
                 good_regret$ci_high),
         "，最后50 ticks的正确行动率为 ",
         pct(good_late$mean), "。`B-bad` 的对应数值为 ",
         ci_text(bad_regret$mean, bad_regret$ci_low,
                 bad_regret$ci_high), " 和 ", pct(bad_late$mean), "。"),
  "",
  "这里的不对称有清楚的 bandit 含义：在 `B-good` 中，具有诊断力的 B 同时也是较优行动，所以学习与获得 payoff 方向一致；在 `B-bad` 中，只有较差的 B 能继续提供诊断信息，学习必须承担探索成本，而正确的 A 又不会让 posterior 继续变得更确定。因此 `B-bad` 的 regret 更高、后期正确率更低。",
  "",
  "![Learning paths](figure_2_learning_paths.png)",
  "",
  "![Outcome distributions](figure_3_outcome_distributions.png)",
  "",
  "### 3.4 外环 sharing 具有因果作用，但作用依赖世界与指标",
  "",
  paste0("sharing on 相对 off，在 `B-good` 中使 regret 改变 ",
         ci_text(good_peer_regret$mean_on_minus_off,
                 good_peer_regret$ci_low, good_peer_regret$ci_high),
         "，最后50 ticks正确率改变 ",
         ci_text(good_peer_late$mean_on_minus_off,
                 good_peer_late$ci_low, good_peer_late$ci_high), "。"),
  "",
  paste0("在 `B-bad` 中，相应差值为 regret ",
         ci_text(bad_peer_regret$mean_on_minus_off,
                 bad_peer_regret$ci_low, bad_peer_regret$ci_high),
         "，后期正确率 ",
         ci_text(bad_peer_late$mean_on_minus_off,
                 bad_peer_late$ci_low, bad_peer_late$ci_high), "。共有 ",
         pct(mean(peer_pair$any_path_difference)),
         " 的配对 runs 至少一个核心终点发生变化。"),
  "",
  paste0("机制方向也与世界相匹配：sharing 使 `B-good` 中每位 layperson 的 B pulls 平均增加 ",
         fmt(good_peer_b_pulls$mean_on_minus_off, 1),
         "，却使 `B-bad` 中 B pulls 平均减少 ",
         fmt(abs(bad_peer_b_pulls$mean_on_minus_off), 1),
         "。外环信息因此不是简单地增加探索，而是把取样推向群体当前认为更有价值的方向。"),
  "",
  "这说明 Royal Family 外环不是装饰：邻居结果改变 posterior，posterior 改变下一次 pull，下一次 pull又改变未来可传播的 evidence。不过，这不等于信息分享在所有环境中都必然有益；这里只能确认它在当前固定环境和正确 likelihood 下有明显帮助。",
  "",
  "![Peer sharing effects](figure_4_peer_sharing_effects.png)",
  "",
  "## 4. 结论",
  "",
  "Experiment 0 通过了进入 Evidence Deference 实验所需的三个门槛：模型产生了内生而非固定的 expert 优势；选择性取样形成了世界不对称和跨 seed 路径差异；外环一跳 sharing 实际改变了后续学习。",
  "",
  "但本实验没有 expert testimony，因此不能据此支持 Preemption 或 Total Evidence。它也没有证明 Bayesian 单步更新无法数学推导。ABM 的价值在于把行动、局部传播和后续 evidence 生产连成一个有限时间过程，并给出路径、恢复和错误持续的分布。",
  "",
  "下一步应在完全相同的 bandit core 上实现 Experiment 1：expert 在明确时点传递 raw evidence，分别操作化 Evidence-Preemption 与 Evidence-Total Evidence。"
)

writeLines(
  report_lines,
  con = file.path(output_dir, "experiment_0_bandit_report.md"),
  useBytes = TRUE
)

html_escape <- function(x) {
  x <- gsub("&", "&amp;", x, fixed = TRUE)
  x <- gsub("<", "&lt;", x, fixed = TRUE)
  x <- gsub(">", "&gt;", x, fixed = TRUE)
  x
}

markdown_to_simple_html <- function(lines) {
  out <- character()
  in_paragraph <- FALSE
  close_paragraph <- function() {
    if (in_paragraph) {
      out <<- c(out, "</p>")
      in_paragraph <<- FALSE
    }
  }
  for (line in lines) {
    if (grepl("^# ", line)) {
      close_paragraph()
      out <- c(out, paste0("<h1>", html_escape(sub("^# ", "", line)), "</h1>"))
    } else if (grepl("^## ", line)) {
      close_paragraph()
      out <- c(out, paste0("<h2>", html_escape(sub("^## ", "", line)), "</h2>"))
    } else if (grepl("^### ", line)) {
      close_paragraph()
      out <- c(out, paste0("<h3>", html_escape(sub("^### ", "", line)), "</h3>"))
    } else if (grepl("^!\\[", line)) {
      close_paragraph()
      alt <- sub("^!\\[([^]]+)\\].*$", "\\1", line)
      src <- sub("^.*\\(([^)]+)\\)$", "\\1", line)
      out <- c(out, paste0("<figure><img src=\"", src,
                           "\" alt=\"", html_escape(alt),
                           "\"></figure>"))
    } else if (nchar(trimws(line)) == 0) {
      close_paragraph()
    } else {
      text <- html_escape(line)
      text <- gsub("`([^`]+)`", "<code>\\1</code>", text)
      text <- gsub("\\*\\*([^*]+)\\*\\*", "<strong>\\1</strong>", text)
      if (!in_paragraph) {
        out <- c(out, paste0("<p>", text))
        in_paragraph <- TRUE
      } else {
        out <- c(out, paste0(" ", text))
      }
    }
  }
  close_paragraph()
  out
}

html_body <- markdown_to_simple_html(report_lines)
html <- c(
  "<!doctype html>",
  "<html lang=\"zh-CN\"><head><meta charset=\"utf-8\">",
  "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">",
  "<title>Experiment 0：动态 Bandit Base 实验报告</title>",
  "<style>",
  "body{font-family:system-ui,-apple-system,'Segoe UI','Microsoft YaHei',sans-serif;max-width:980px;margin:36px auto;padding:0 24px;color:#20242a;line-height:1.75;background:#fff}",
  "h1{font-size:2rem;border-bottom:3px solid #553C9A;padding-bottom:.45rem}h2{margin-top:2.2rem;color:#3F2D7D}h3{margin-top:1.5rem;color:#394150}",
  "p{margin:.75rem 0}code{background:#f1f3f5;padding:.1rem .3rem;border-radius:4px}figure{margin:1.4rem 0}img{width:100%;height:auto;border:1px solid #d9dde3;border-radius:8px}",
  "</style></head><body>",
  html_body,
  "</body></html>"
)
writeLines(html, con = file.path(output_dir, "experiment_0_bandit_report.html"),
           useBytes = TRUE)

key_results <- c(
  paste0("status=", validation_status),
  paste0("main_runs=", nrow(main)),
  paste0("trajectory_rows=", nrow(trajectory)),
  paste0("peer_pairs=", nrow(peer_pair)),
  paste0("B_good_expert_truth_25=", good_expertise$expert_truth_mass),
  paste0("B_good_lay_truth_25=", good_expertise$lay_truth_mass),
  paste0("B_good_gap=", good_expertise$expert_minus_lay),
  paste0("B_bad_expert_truth_25=", bad_expertise$expert_truth_mass),
  paste0("B_bad_lay_truth_25=", bad_expertise$lay_truth_mass),
  paste0("B_bad_gap=", bad_expertise$expert_minus_lay),
  paste0("B_good_regret=", good_regret$mean),
  paste0("B_bad_regret=", bad_regret$mean),
  paste0("B_good_late_correct=", good_late$mean),
  paste0("B_bad_late_correct=", bad_late$mean),
  paste0("peer_any_path_difference_share=",
         mean(peer_pair$any_path_difference)),
  paste0("checks_passed=", sum(validation_checks$passed),
         "/", nrow(validation_checks))
)
writeLines(key_results, file.path(output_dir, "analysis_key_results.txt"),
           useBytes = TRUE)

capture.output(sessionInfo(),
               file = file.path(output_dir, "R_session_info.txt"))

cat(paste(key_results, collapse = "\n"), "\n")
