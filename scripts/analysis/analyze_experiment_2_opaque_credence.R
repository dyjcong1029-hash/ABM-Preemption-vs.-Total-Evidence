options(stringsAsFactors = FALSE, scipen = 999)

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 7) {
  stop(paste(
    "Usage: Rscript analyze_experiment_2_opaque_credence.R",
    "<main> <trajectories> <exact-trajectories> <exp1-trajectories>",
    "<frozen-table> <heldout-audit> <output-dir>"
  ))
}

main_path <- args[[1]]
trajectory_path <- args[[2]]
exact_path <- args[[3]]
exp1_path <- args[[4]]
frozen_path <- args[[5]]
heldout_path <- args[[6]]
output_dir <- args[[7]]
dir.create(output_dir, recursive = TRUE, showWarnings = FALSE)

clean_names <- function(x) {
  x <- tolower(x)
  x <- gsub("\\?", "", x)
  x <- gsub("[^a-z0-9]+", "_", x)
  x <- gsub("^_+|_+$", "", x)
  make.unique(x, sep = "_")
}

read_behaviorspace <- function(path) {
  x <- read.csv(
    path, skip = 6, check.names = FALSE, stringsAsFactors = FALSE,
    na.strings = c("NA", "NaN")
  )
  names(x) <- clean_names(names(x))
  x
}

write_utf8 <- function(x, name) {
  write.csv(
    x, file.path(output_dir, name), row.names = FALSE,
    na = "", fileEncoding = "UTF-8"
  )
}

as_flag <- function(x) {
  if (is.logical(x)) return(x)
  tolower(as.character(x)) == "true"
}

assert_columns <- function(x, required, label) {
  missing <- setdiff(required, names(x))
  if (length(missing) > 0) {
    stop(sprintf("%s missing columns: %s", label, paste(missing, collapse = ", ")))
  }
}

bootstrap_mean_ci <- function(x, B = 10000L, seed = 1L) {
  x <- as.numeric(x)
  x <- x[is.finite(x)]
  if (length(x) == 0) return(c(estimate = NA, low = NA, high = NA))
  if (length(x) == 1) return(c(estimate = x, low = x, high = x))
  set.seed(seed)
  boot <- replicate(B, mean(sample(x, length(x), replace = TRUE)))
  c(
    estimate = mean(x),
    low = unname(quantile(boot, 0.025, names = FALSE)),
    high = unname(quantile(boot, 0.975, names = FALSE))
  )
}

paired_values <- function(data, world, policy_1, policy_0, column, status = NULL) {
  d <- data[data$hidden_world == world, ]
  if (!is.null(status)) d <- d[d$message_status == status, ]
  a <- d[d$credence_policy == policy_1, c("actual_seed", column)]
  b <- d[d$credence_policy == policy_0, c("actual_seed", column)]
  names(a)[2] <- "a"
  names(b)[2] <- "b"
  m <- merge(a, b, by = "actual_seed", all = FALSE)
  m <- m[order(m$actual_seed), ]
  data.frame(actual_seed = m$actual_seed, difference = m$a - m$b)
}

max_within_block_range <- function(data, columns) {
  key <- interaction(data$hidden_world, data$actual_seed, drop = TRUE)
  max(vapply(columns, function(column) {
    ranges <- tapply(data[[column]], key, function(x) max(x) - min(x))
    max(ranges, na.rm = TRUE)
  }, numeric(1)))
}

main <- read_behaviorspace(main_path)
trajectory <- read_behaviorspace(trajectory_path)
exact <- read_behaviorspace(exact_path)
exp1 <- read_behaviorspace(exp1_path)
frozen <- read.csv(frozen_path, stringsAsFactors = FALSE, check.names = FALSE)
heldout <- read.csv(heldout_path, stringsAsFactors = FALSE, check.names = FALSE)

required_main <- c(
  "actual_seed", "hidden_world", "credence_policy", "ticks",
  "report_table_version", "expert_total_pulls", "total_lay_pulls",
  "expert_truth_mass_at_25", "expert_recommendation_score_at_25",
  "expert_informative_observations_at_25", "mean_lay_truth_mass_at_25",
  "mean_lay_llr_at_25", "mean_lay_recommendation_score_at_25",
  "mean_lay_informative_observations_at_25", "mean_lay_archive_size_at_25",
  "mean_lay_cumulative_regret_at_25", "private_expert_q_at_intervention",
  "private_expert_llr_at_intervention", "broadcast_message_bin",
  "broadcast_message_midpoint", "broadcast_message_llr",
  "broadcast_message_mode", "expert_report_direction_accuracy",
  "credence_message_count", "expert_raw_items_transmitted",
  "inbox_empty_at_intervention", "maximum_message_bin_copy_error",
  "maximum_message_llr_copy_error", "maximum_immediate_policy_formula_error",
  "mean_received_message_bin_post_intervention",
  "received_bin_dispersion_post_intervention",
  "mean_received_message_llr_post_intervention",
  "received_message_llr_dispersion_post_intervention",
  "mean_lay_truth_mass_post_intervention", "lay_q_dispersion_post_intervention",
  "mean_lay_local_archive_size_post_intervention",
  "mean_lay_active_decision_inputs_post_intervention",
  "mean_lay_post_intervention_regret", "early_window_wrong_choice_rate",
  "post_intervention_correct_choice_rate", "final_window_correct_choice_rate",
  "final_window_wrong_choice_rate", "mean_lay_final_brier_score",
  "mean_lay_posterior_truth_mass", "mean_lay_q",
  "mean_lay_cumulative_regret", "mean_lay_realized_payoff",
  "post_intervention_realized_payoff", "mean_lay_b_pulls",
  "maximum_local_ledger_identity_error", "maximum_regret_identity_error",
  "maximum_decision_decomposition_error", "network_structure_valid",
  "message_accounting_valid", "evidence_provenance_valid",
  "credence_payload_valid", "credence_intervention_valid"
)
required_trajectory <- c(
  "actual_seed", "hidden_world", "credence_policy", "ticks",
  "report_table_version", "broadcast_message_bin", "broadcast_message_llr",
  "private_expert_q_at_intervention", "current_lay_correct_choice_rate",
  "current_lay_b_share", "mean_lay_q", "mean_lay_posterior_truth_mass",
  "mean_lay_final_brier_score", "mean_lay_cumulative_regret",
  "mean_lay_post_intervention_regret", "expert_posterior_truth_mass",
  "expert_total_pulls", "maximum_local_ledger_identity_error",
  "maximum_decision_decomposition_error", "message_accounting_valid"
)
assert_columns(main, required_main, "main")
assert_columns(trajectory, required_trajectory, "trajectory")
assert_columns(exact, required_trajectory, "exact regression")

policies <- c("No Deference", "C-Preemption", "C-Total Evidence")
worlds <- c("B-good", "B-bad")

main$message_status <- ifelse(
  abs(main$broadcast_message_llr) < 1e-12, "Neutral",
  ifelse(
    (main$hidden_world == "B-good" & main$broadcast_message_llr > 0) |
      (main$hidden_world == "B-bad" & main$broadcast_message_llr < 0),
    "Correct", "Incorrect"
  )
)

main <- main[order(
  main$hidden_world, main$actual_seed,
  match(main$credence_policy, policies)
), ]
trajectory <- trajectory[order(
  trajectory$hidden_world, trajectory$actual_seed,
  match(trajectory$credence_policy, policies), trajectory$ticks
), ]

main_clean <- main[, c(required_main, "message_status")]
write_utf8(main_clean, "main_run_level_clean.csv")

cell_counts <- as.data.frame(table(main$hidden_world, main$credence_policy))
names(cell_counts) <- c("world", "policy", "n_runs")
cell_counts <- cell_counts[cell_counts$n_runs > 0, ]

block_policy_counts <- table(interaction(main$hidden_world, main$actual_seed, drop = TRUE))
pretreatment_columns <- c(
  "expert_truth_mass_at_25", "expert_recommendation_score_at_25",
  "expert_informative_observations_at_25", "mean_lay_truth_mass_at_25",
  "mean_lay_llr_at_25", "mean_lay_recommendation_score_at_25",
  "mean_lay_informative_observations_at_25", "mean_lay_archive_size_at_25",
  "mean_lay_cumulative_regret_at_25", "private_expert_q_at_intervention",
  "private_expert_llr_at_intervention", "broadcast_message_bin",
  "broadcast_message_llr"
)
pretreatment_max_range <- max_within_block_range(main, pretreatment_columns)

flag_columns <- c(
  "inbox_empty_at_intervention", "network_structure_valid",
  "message_accounting_valid", "evidence_provenance_valid",
  "credence_payload_valid", "credence_intervention_valid"
)
all_flags_true <- all(vapply(flag_columns, function(x) all(as_flag(main[[x]])), logical(1)))

calibration_seed_ranges <- c(1000001:1050000, 1100001:1150000,
                             2000001:2010000, 2100001:2110000)
main_calibration_seed_overlap <- length(intersect(unique(main$actual_seed), calibration_seed_ranges))

checks <- data.frame(
  check = c(
    "main_has_3000_network_runs",
    "each_world_policy_cell_has_500_runs",
    "each_world_seed_block_has_three_policies",
    "main_seeds_are_510001_to_510500",
    "main_and_calibration_seeds_do_not_overlap",
    "all_runs_end_at_tick_500",
    "expert_has_exactly_125_pulls",
    "each_run_has_5000_lay_pulls",
    "lay_archive_has_75_items_at_intervention",
    "no_raw_expert_items_transmitted",
    "one_credence_message_per_run",
    "one_frozen_table_version",
    "pretreatment_paths_identical_across_policies",
    "all_structural_and_intervention_flags_true",
    "ledger_errors_below_1e_10",
    "trajectory_has_601200_rows",
    "trajectory_has_501_rows_per_run",
    "exact_regression_has_400800_rows"
  ),
  value = c(
    nrow(main),
    paste(sort(unique(cell_counts$n_runs)), collapse = ","),
    paste(sort(unique(as.integer(block_policy_counts))), collapse = ","),
    paste(range(main$actual_seed), collapse = "-"),
    main_calibration_seed_overlap,
    paste(sort(unique(main$ticks)), collapse = ","),
    paste(sort(unique(main$expert_total_pulls)), collapse = ","),
    paste(sort(unique(main$total_lay_pulls)), collapse = ","),
    max(abs(main$mean_lay_archive_size_at_25 - 75)),
    max(main$expert_raw_items_transmitted),
    paste(sort(unique(main$credence_message_count)), collapse = ","),
    length(unique(main$report_table_version)),
    pretreatment_max_range,
    all_flags_true,
    max(abs(c(
      main$maximum_local_ledger_identity_error,
      main$maximum_regret_identity_error,
      main$maximum_decision_decomposition_error,
      main$maximum_message_bin_copy_error,
      main$maximum_message_llr_copy_error,
      main$maximum_immediate_policy_formula_error
    ))),
    nrow(trajectory),
    paste(sort(unique(as.integer(table(interaction(
      trajectory$hidden_world, trajectory$actual_seed,
      trajectory$credence_policy, drop = TRUE
    ))))), collapse = ","),
    nrow(exact)
  ),
  passed = c(
    nrow(main) == 3000,
    nrow(cell_counts) == 6 && all(cell_counts$n_runs == 500),
    length(block_policy_counts) == 1000 && all(block_policy_counts == 3),
    identical(sort(unique(main$actual_seed)), 510001:510500),
    main_calibration_seed_overlap == 0,
    all(main$ticks == 500),
    all(main$expert_total_pulls == 125),
    all(main$total_lay_pulls == 5000),
    all(abs(main$mean_lay_archive_size_at_25 - 75) < 1e-12),
    all(main$expert_raw_items_transmitted == 0),
    all(main$credence_message_count == 1),
    length(unique(main$report_table_version)) == 1,
    pretreatment_max_range < 1e-12,
    all_flags_true,
    max(abs(c(
      main$maximum_local_ledger_identity_error,
      main$maximum_regret_identity_error,
      main$maximum_decision_decomposition_error,
      main$maximum_message_bin_copy_error,
      main$maximum_message_llr_copy_error,
      main$maximum_immediate_policy_formula_error
    ))) < 1e-10,
    nrow(trajectory) == 601200,
    all(table(interaction(
      trajectory$hidden_world, trajectory$actual_seed,
      trajectory$credence_policy, drop = TRUE
    )) == 501),
    nrow(exact) == 400800
  ),
  stringsAsFactors = FALSE
)

# Endpoint levels by world and policy.
endpoint_columns <- c(
  post_regret = "mean_lay_post_intervention_regret",
  early_wrong_rate = "early_window_wrong_choice_rate",
  post_correct_rate = "post_intervention_correct_choice_rate",
  late_correct_rate = "final_window_correct_choice_rate",
  final_brier = "mean_lay_final_brier_score"
)
endpoint_rows <- list()
idx <- 1L
for (world in worlds) {
  for (policy in policies) {
    d <- main[main$hidden_world == world & main$credence_policy == policy, ]
    for (metric in names(endpoint_columns)) {
      values <- d[[endpoint_columns[[metric]]]]
      endpoint_rows[[idx]] <- data.frame(
        world = world, policy = policy, metric = metric,
        n_runs = length(values), mean = mean(values), sd = sd(values),
        se = sd(values) / sqrt(length(values)),
        stringsAsFactors = FALSE
      )
      idx <- idx + 1L
    }
  }
}
endpoint_summary <- do.call(rbind, endpoint_rows)
write_utf8(endpoint_summary, "endpoint_summary.csv")

# Paired policy effects. The complete network run is the unit.
comparisons <- list(
  c("C-Preemption", "No Deference"),
  c("C-Total Evidence", "No Deference"),
  c("C-Total Evidence", "C-Preemption")
)
effect_rows <- list()
idx <- 1L
for (world in worlds) {
  for (pair in comparisons) {
    for (metric in names(endpoint_columns)) {
      d <- paired_values(main, world, pair[[1]], pair[[2]], endpoint_columns[[metric]])
      ci <- bootstrap_mean_ci(d$difference, B = 10000L, seed = 10000L + idx)
      effect_rows[[idx]] <- data.frame(
        world = world,
        comparison = paste(pair[[1]], "-", pair[[2]]),
        policy_1 = pair[[1]], policy_0 = pair[[2]], metric = metric,
        n_pairs = nrow(d), estimate = ci[["estimate"]],
        ci_low = ci[["low"]], ci_high = ci[["high"]],
        stringsAsFactors = FALSE
      )
      idx <- idx + 1L
    }
  }
}
paired_effects <- do.call(rbind, effect_rows)
write_utf8(paired_effects, "paired_policy_effects.csv")

# Message-direction mechanism description.
status_counts <- unique(main[, c("hidden_world", "actual_seed", "message_status")])
status_counts <- aggregate(actual_seed ~ hidden_world + message_status, status_counts, length)
names(status_counts)[3] <- "n_blocks"
write_utf8(status_counts, "message_status_counts.csv")

conditional_rows <- list()
idx <- 1L
for (world in worlds) {
  for (status in c("Correct", "Incorrect", "Neutral")) {
    if (!any(main$hidden_world == world & main$message_status == status)) next
    for (metric in c("post_regret", "early_wrong_rate", "late_correct_rate", "final_brier")) {
      d <- paired_values(
        main, world, "C-Total Evidence", "C-Preemption",
        endpoint_columns[[metric]], status
      )
      if (nrow(d) == 0) next
      ci <- if (nrow(d) >= 30) {
        bootstrap_mean_ci(d$difference, B = 10000L, seed = 20000L + idx)
      } else {
        c(estimate = mean(d$difference), low = NA, high = NA)
      }
      conditional_rows[[idx]] <- data.frame(
        world = world, message_status = status, metric = metric,
        n_pairs = nrow(d), estimate = ci[["estimate"]],
        ci_low = ci[["low"]], ci_high = ci[["high"]],
        stringsAsFactors = FALSE
      )
      idx <- idx + 1L
    }
  }
}
conditional_effects <- do.call(rbind, conditional_rows)
write_utf8(conditional_effects, "conditional_message_effects.csv")

# Recovery: first start of 20 consecutive rounds with network correct share >= .60.
status_key <- unique(main[, c("hidden_world", "actual_seed", "message_status")])
trajectory <- merge(
  trajectory, status_key,
  by = c("hidden_world", "actual_seed"), all.x = TRUE, sort = FALSE
)
trajectory <- trajectory[order(
  trajectory$hidden_world, trajectory$actual_seed,
  match(trajectory$credence_policy, policies), trajectory$ticks
), ]

recovery_for_run <- function(ticks, correct) {
  keep <- ticks >= 26 & ticks <= 500
  ticks <- ticks[keep]
  correct <- correct[keep]
  if (length(ticks) != 475) return(c(delay = NA, recovered = FALSE))
  good <- correct >= 0.60
  run20 <- as.logical(stats::filter(as.numeric(good), rep(1, 20), sides = 1) == 20)
  run20[is.na(run20)] <- FALSE
  ends <- which(run20)
  if (length(ends) == 0) return(c(delay = 476, recovered = FALSE))
  start_tick <- ticks[ends[[1]]] - 19
  c(delay = start_tick - 25, recovered = TRUE)
}

split_key <- interaction(
  trajectory$hidden_world, trajectory$actual_seed,
  trajectory$credence_policy, drop = TRUE
)
groups <- split(seq_len(nrow(trajectory)), split_key)
recovery_rows <- lapply(groups, function(rows) {
  d <- trajectory[rows, ]
  r <- recovery_for_run(d$ticks, d$current_lay_correct_choice_rate)
  data.frame(
    world = d$hidden_world[[1]], actual_seed = d$actual_seed[[1]],
    policy = d$credence_policy[[1]], message_status = d$message_status[[1]],
    restricted_recovery_delay = as.numeric(r[["delay"]]),
    recovered_by_tick_500 = as.logical(r[["recovered"]]),
    stringsAsFactors = FALSE
  )
})
recovery_run_level <- do.call(rbind, recovery_rows)
write_utf8(recovery_run_level, "recovery_run_level.csv")

recovery_effect_rows <- list()
idx <- 1L
for (world in worlds) {
  for (status in c("Incorrect", "Correct", "Neutral")) {
    d0 <- recovery_run_level[
      recovery_run_level$world == world &
        recovery_run_level$message_status == status, ]
    if (nrow(d0) == 0) next
    a <- d0[d0$policy == "C-Total Evidence", c("actual_seed", "restricted_recovery_delay", "recovered_by_tick_500")]
    b <- d0[d0$policy == "C-Preemption", c("actual_seed", "restricted_recovery_delay", "recovered_by_tick_500")]
    m <- merge(a, b, by = "actual_seed", suffixes = c("_te", "_p"))
    diff <- m$restricted_recovery_delay_te - m$restricted_recovery_delay_p
    ci <- if (nrow(m) >= 30) bootstrap_mean_ci(diff, 10000L, 30000L + idx) else c(estimate = mean(diff), low = NA, high = NA)
    recovery_effect_rows[[idx]] <- data.frame(
      world = world, message_status = status, n_pairs = nrow(m),
      te_minus_preemption_delay = ci[["estimate"]],
      ci_low = ci[["low"]], ci_high = ci[["high"]],
      te_not_recovered_rate = mean(!m$recovered_by_tick_500_te),
      preemption_not_recovered_rate = mean(!m$recovered_by_tick_500_p),
      stringsAsFactors = FALSE
    )
    idx <- idx + 1L
  }
}
recovery_summary <- do.call(rbind, recovery_effect_rows)
write_utf8(recovery_summary, "recovery_summary.csv")

# Trajectory chart data: full 200-seed trajectory sample, displayed every 5 ticks
# plus the intervention boundary.
display_ticks <- sort(unique(c(seq(0, 500, by = 5), 25, 26)))
td <- trajectory[trajectory$ticks %in% display_ticks, ]
trajectory_chart <- aggregate(
  cbind(
    correct_share = td$current_lay_correct_choice_rate,
    post_regret = td$mean_lay_post_intervention_regret,
    mean_q = td$mean_lay_q
  ) ~ hidden_world + credence_policy + ticks,
  data = td, FUN = mean
)
names(trajectory_chart)[1:2] <- c("world", "policy")
write_utf8(trajectory_chart, "trajectory_chart_data.csv")

# Exact-message regression against Experiment 1. This is validation only.
exact$mapped_exp1_policy <- ifelse(
  exact$credence_policy == "Exact-C-Preemption", "E-Preemption",
  ifelse(exact$credence_policy == "Exact-C-Total Evidence", "E-Total Evidence", NA)
)
exp1 <- exp1[exp1$evidence_policy %in% c("E-Preemption", "E-Total Evidence"), ]
common_metrics <- c(
  "current_lay_correct_choice_rate", "current_lay_b_share", "mean_lay_q",
  "mean_lay_posterior_truth_mass", "mean_lay_cumulative_regret",
  "mean_lay_post_intervention_regret", "expert_posterior_truth_mass",
  "expert_total_pulls"
)
assert_columns(exp1, c("actual_seed", "hidden_world", "evidence_policy", "ticks", common_metrics), "Experiment 1 trajectory")
exact_subset <- exact[, c("actual_seed", "hidden_world", "mapped_exp1_policy", "ticks", common_metrics)]
exp1_subset <- exp1[, c("actual_seed", "hidden_world", "evidence_policy", "ticks", common_metrics)]
names(exact_subset)[3] <- "policy"
names(exp1_subset)[3] <- "policy"
regression <- merge(
  exact_subset, exp1_subset,
  by = c("actual_seed", "hidden_world", "policy", "ticks"),
  suffixes = c("_exact", "_exp1"), all = TRUE, sort = FALSE
)
exact_rows_complete <- nrow(regression) == 400800 && !any(!complete.cases(regression))
regression_metrics <- lapply(common_metrics, function(metric) {
  difference <- regression[[paste0(metric, "_exact")]] - regression[[paste0(metric, "_exp1")]]
  data.frame(
    metric = metric,
    max_absolute_difference = max(abs(difference), na.rm = TRUE),
    mismatch_count_1e_10 = sum(abs(difference) > 1e-10, na.rm = TRUE),
    stringsAsFactors = FALSE
  )
})
exact_regression <- do.call(rbind, regression_metrics)
action_mismatch <- sum(
  exact_regression$metric %in% c("current_lay_correct_choice_rate", "current_lay_b_share") &
    exact_regression$mismatch_count_1e_10 > 0
)
exact_pass <- exact_rows_complete &&
  max(exact_regression$max_absolute_difference) <= 1e-10 &&
  action_mismatch == 0
write_utf8(exact_regression, "exact_message_regression.csv")

checks <- rbind(
  checks,
  data.frame(
    check = c(
      "exact_regression_rows_align_with_experiment_1",
      "exact_regression_max_difference_below_1e_10",
      "exact_regression_action_aggregate_mismatches_zero"
    ),
    value = c(
      exact_rows_complete,
      max(exact_regression$max_absolute_difference),
      action_mismatch
    ),
    passed = c(
      exact_rows_complete,
      max(exact_regression$max_absolute_difference) <= 1e-10,
      action_mismatch == 0
    ),
    stringsAsFactors = FALSE
  )
)
write_utf8(checks, "validation_checks.csv")

# Three report figures.
main_effect <- paired_effects[
  paired_effects$comparison == "C-Total Evidence - C-Preemption" &
    paired_effects$metric == "post_regret", ]
main_effect <- main_effect[match(worlds, main_effect$world), ]

png(file.path(output_dir, "figure_1_main_regret_effect.png"), width = 1500, height = 850, res = 160, type = "cairo-png")
par(mar = c(5, 11, 3, 2), family = "sans")
y <- c(2, 1)
xlim <- range(c(main_effect$ci_low, main_effect$ci_high, 0))
padding <- max(0.05, diff(xlim) * 0.20)
plot(
  main_effect$estimate, y, xlim = xlim + c(-padding, padding), ylim = c(0.5, 2.5),
  yaxt = "n", ylab = "", xlab = "TE minus Preemption: rounds 26-500 expected regret",
  pch = 19, cex = 1.5, col = "#2F6B9A", bty = "n", main = "Paired policy effect by hidden world"
)
axis(2, at = y, labels = c("B-good", "B-bad"), las = 1)
abline(v = 0, lty = 2, col = "#555555")
segments(main_effect$ci_low, y, main_effect$ci_high, y, lwd = 3, col = "#2F6B9A")
points(main_effect$estimate, y, pch = 19, cex = 1.5, col = "#2F6B9A")
text(main_effect$estimate, y + 0.18, labels = sprintf("%.3f", main_effect$estimate), cex = 0.9)
mtext("Negative values mean retaining local credence produced less loss", side = 1, line = 3.7, cex = 0.85)
dev.off()

png(file.path(output_dir, "figure_2_learning_trajectories.png"), width = 1700, height = 850, res = 160, type = "cairo-png")
par(mfrow = c(1, 2), mar = c(5, 5, 3, 1), family = "sans")
colors <- c("No Deference" = "#888888", "C-Preemption" = "#D07A2D", "C-Total Evidence" = "#2F6B9A")
line_types <- c("No Deference" = 3, "C-Preemption" = 2, "C-Total Evidence" = 1)
for (world in worlds) {
  plot(0, 0, type = "n", xlim = c(0, 500), ylim = c(0, 1),
       xlab = "Round", ylab = "Mean share choosing the better arm",
       main = world, bty = "n")
  abline(v = 25, lty = 3, col = "#555555")
  abline(h = 0.5, lty = 3, col = "#CCCCCC")
  for (policy in policies) {
    d <- trajectory_chart[trajectory_chart$world == world & trajectory_chart$policy == policy, ]
    d <- d[order(d$ticks), ]
    lines(d$ticks, d$correct_share, col = colors[[policy]], lty = line_types[[policy]], lwd = 2.5)
  }
  legend("bottomright", legend = policies, col = colors[policies], lty = line_types[policies], lwd = 2.5, bty = "n", cex = 0.85)
}
dev.off()

png(file.path(output_dir, "figure_3_calibration_check.png"), width = 1500, height = 850, res = 160, type = "cairo-png")
par(mar = c(5, 5, 3, 2), family = "sans")
plot(
  heldout$midpoint, heldout$frozen_implied_p_good,
  type = "b", pch = 19, lwd = 2.5, col = "#2F6B9A", ylim = c(0, 1),
  xlab = "Reported credence category midpoint", ylab = "P(B-good | message)",
  main = "Frozen message semantics and held-out validation", bty = "n"
)
segments(
  heldout$midpoint, heldout$wilson_low,
  heldout$midpoint, heldout$wilson_high,
  col = "#D07A2D", lwd = 2
)
points(heldout$midpoint, heldout$heldout_empirical_p_good, pch = 1, cex = 1.4, lwd = 2, col = "#D07A2D")
abline(0, 1, lty = 3, col = "#777777")
legend(
  "topleft", c("Frozen table", "Held-out empirical (95% Wilson interval)"),
  col = c("#2F6B9A", "#D07A2D"), pch = c(19, 1), lty = c(1, NA), lwd = 2, bty = "n"
)
dev.off()

headline <- main_effect[, c("world", "n_pairs", "estimate", "ci_low", "ci_high")]
write_utf8(headline, "headline_results.csv")

status <- if (all(checks$passed)) "READY" else "NOT READY"
key_lines <- c(
  sprintf("Analysis status: %s", status),
  sprintf("Validation checks passed: %d/%d", sum(checks$passed), nrow(checks)),
  sprintf(
    "B-good TE-P post-regret: %.6f [%.6f, %.6f]",
    headline$estimate[headline$world == "B-good"],
    headline$ci_low[headline$world == "B-good"],
    headline$ci_high[headline$world == "B-good"]
  ),
  sprintf(
    "B-bad TE-P post-regret: %.6f [%.6f, %.6f]",
    headline$estimate[headline$world == "B-bad"],
    headline$ci_low[headline$world == "B-bad"],
    headline$ci_high[headline$world == "B-bad"]
  ),
  sprintf("Exact-message regression max difference: %.3g", max(exact_regression$max_absolute_difference))
)
writeLines(key_lines, file.path(output_dir, "analysis_key_results.txt"), useBytes = TRUE)
writeLines(capture.output(sessionInfo()), file.path(output_dir, "R_session_info.txt"), useBytes = TRUE)

cat(paste(key_lines, collapse = "\n"), "\n")
if (!all(checks$passed)) stop("Validation failed; report conclusions must not be generated")
