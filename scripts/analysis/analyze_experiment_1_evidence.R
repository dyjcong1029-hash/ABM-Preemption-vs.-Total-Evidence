options(stringsAsFactors = FALSE, scipen = 999)

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 5) {
  stop(paste(
    "Usage: Rscript analyze_experiment_1_evidence.R",
    "<exp1-main> <exp1-trajectories> <exp0-main> <exp0-trajectories> <output-dir>"
  ))
}

main_path <- args[[1]]
trajectory_path <- args[[2]]
exp0_main_path <- args[[3]]
exp0_trajectory_path <- args[[4]]
output_dir <- args[[5]]
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
    path,
    skip = 6,
    check.names = FALSE,
    stringsAsFactors = FALSE,
    na.strings = c("NA", "NaN")
  )
  names(x) <- clean_names(names(x))
  x
}

write_csv_utf8 <- function(x, filename) {
  write.csv(
    x,
    file.path(output_dir, filename),
    row.names = FALSE,
    na = "",
    fileEncoding = "UTF-8"
  )
}

as_flag <- function(x) {
  if (is.logical(x)) return(x)
  tolower(as.character(x)) == "true"
}

assert_columns <- function(x, columns, label) {
  missing <- setdiff(columns, names(x))
  if (length(missing) > 0) {
    stop(sprintf("%s is missing columns: %s", label, paste(missing, collapse = ", ")))
  }
}

bootstrap_mean_ci <- function(x, B = 4000, seed = 1L) {
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

cell_summary <- function(x, seed = 1L) {
  z <- bootstrap_mean_ci(x, seed = seed)
  c(mean = z[["estimate"]], ci_low = z[["low"]], ci_high = z[["high"]])
}

range_within <- function(x, key) {
  values <- tapply(x, key, function(v) max(v) - min(v))
  max(values, na.rm = TRUE)
}

max_abs_difference <- function(x, y) {
  if (length(x) != length(y)) return(Inf)
  max(abs(as.numeric(x) - as.numeric(y)), na.rm = TRUE)
}

main <- read_behaviorspace(main_path)
trajectory <- read_behaviorspace(trajectory_path)
exp0_main <- read_behaviorspace(exp0_main_path)
exp0_trajectory <- read_behaviorspace(exp0_trajectory_path)

required_main <- c(
  "actual_seed", "hidden_world", "evidence_policy", "ticks",
  "expert_total_pulls", "total_lay_pulls",
  "expert_truth_mass_at_25", "expert_recommendation_score_at_25",
  "expert_informative_observations_at_25",
  "mean_lay_truth_mass_at_25", "mean_lay_recommendation_score_at_25",
  "mean_lay_informative_observations_at_25", "mean_lay_archive_size_at_25",
  "mean_lay_cumulative_regret_at_25", "mean_lay_correct_pulls_at_25",
  "mean_lay_b_pulls_at_25", "mean_lay_reward_at_25",
  "expert_packet_size_at_intervention", "expert_packet_informative_count",
  "expert_packet_llr_from_raw", "expert_packet_unique",
  "inbox_empty_at_intervention", "expert_local_overlap_count", "broadcast_count",
  "mean_lay_truth_mass_post_intervention",
  "mean_lay_recommendation_score_post_intervention",
  "lay_q_dispersion_post_intervention",
  "mean_lay_decision_evidence_post_intervention",
  "mean_lay_archive_size_post_intervention",
  "mean_lay_active_evidence_items_post_intervention",
  "maximum_intervention_identity_error", "maximum_expert_packet_llr_error",
  "mean_lay_post_intervention_regret", "post_intervention_correct_choice_rate",
  "post_intervention_realized_payoff", "mean_lay_post_intervention_b_pulls",
  "early_window_correct_choice_rate", "early_window_wrong_choice_rate",
  "early_window_b_share", "mean_lay_posterior_truth_mass",
  "cumulative_lay_correct_choice_rate", "mean_lay_cumulative_regret",
  "mean_lay_realized_payoff", "mean_lay_b_pulls",
  "mean_lay_informative_observations", "mean_lay_active_evidence_items",
  "mean_lay_total_archive_size", "mean_expert_evidence_items_received",
  "final_window_wrong_choice_rate", "finite_horizon_error_persistence_rate",
  "run_finite_horizon_persistent_error", "expert_posterior_truth_mass",
  "expert_recommendation_accuracy", "expert_thompson_correct_rate",
  "expert_cumulative_regret", "expert_b_pull_rate",
  "lay_a_reward_rate", "lay_b_reward_rate", "expert_a_reward_rate",
  "expert_b_reward_rate", "mean_peer_messages_received",
  "mean_unique_evidence_count", "duplicate_message_count",
  "maximum_belief_identity_error", "maximum_regret_identity_error",
  "maximum_decision_decomposition_error", "network_structure_valid",
  "message_accounting_valid", "evidence_provenance_valid",
  "expert_evidence_provenance_valid", "expert_packet_valid",
  "intervention_structure_valid"
)

required_trajectory <- c(
  "actual_seed", "hidden_world", "evidence_policy", "ticks",
  "current_lay_correct_choice_rate", "current_lay_b_share",
  "current_lay_wrong_posterior_share", "mean_lay_q",
  "mean_lay_posterior_truth_mass", "lay_q_dispersion",
  "mean_lay_cumulative_regret", "mean_lay_post_intervention_regret",
  "mean_lay_b_pulls", "expert_posterior_truth_mass",
  "expert_recommendation_accuracy", "expert_total_pulls",
  "maximum_belief_identity_error", "maximum_decision_decomposition_error",
  "message_accounting_valid"
)

assert_columns(main, required_main, "Experiment 1 final data")
assert_columns(trajectory, required_trajectory, "Experiment 1 trajectory data")

policies <- c("No Deference", "E-Preemption", "E-Total Evidence")
worlds <- c("B-good", "B-bad")
main$expert_status <- ifelse(
  abs(main$expert_recommendation_score_at_25 - 1) < 1e-12,
  "Correct",
  ifelse(
    abs(main$expert_recommendation_score_at_25) < 1e-12,
    "Incorrect",
    "Tie"
  )
)

main <- main[order(main$hidden_world, main$actual_seed, match(main$evidence_policy, policies)), ]
trajectory <- trajectory[order(
  trajectory$hidden_world,
  trajectory$actual_seed,
  match(trajectory$evidence_policy, policies),
  trajectory$ticks
), ]

main_clean <- main[, required_main]
main_clean$expert_status <- main$expert_status
write_csv_utf8(main_clean, "main_run_level_clean.csv")

endpoint_metrics <- c(
  post_regret = "mean_lay_post_intervention_regret",
  early_wrong_rate = "early_window_wrong_choice_rate",
  post_correct_rate = "post_intervention_correct_choice_rate",
  post_payoff = "post_intervention_realized_payoff",
  post_b_pulls = "mean_lay_post_intervention_b_pulls",
  final_truth_mass = "mean_lay_posterior_truth_mass",
  late_wrong_rate = "final_window_wrong_choice_rate",
  persistent_run_rate = "run_finite_horizon_persistent_error"
)

endpoint_rows <- list()
endpoint_index <- 1L
for (w in worlds) {
  for (p in policies) {
    d <- main[main$hidden_world == w & main$evidence_policy == p, ]
    row <- data.frame(world = w, policy = p, n_runs = nrow(d), stringsAsFactors = FALSE)
    for (j in seq_along(endpoint_metrics)) {
      output_name <- names(endpoint_metrics)[[j]]
      input_name <- endpoint_metrics[[j]]
      values <- if (input_name == "run_finite_horizon_persistent_error") {
        as.numeric(as_flag(d[[input_name]]))
      } else {
        as.numeric(d[[input_name]])
      }
      s <- cell_summary(values, seed = 1000 + endpoint_index * 50 + j)
      row[[output_name]] <- s[["mean"]]
      row[[paste0(output_name, "_low")]] <- s[["ci_low"]]
      row[[paste0(output_name, "_high")]] <- s[["ci_high"]]
    }
    endpoint_rows[[endpoint_index]] <- row
    endpoint_index <- endpoint_index + 1L
  }
}
endpoint_summary <- do.call(rbind, endpoint_rows)
write_csv_utf8(endpoint_summary, "endpoint_summary.csv")

contrast_specs <- list(
  list(label = "E-Preemption - No Deference", p1 = "E-Preemption", p0 = "No Deference"),
  list(label = "E-Total Evidence - No Deference", p1 = "E-Total Evidence", p0 = "No Deference"),
  list(label = "E-Total Evidence - E-Preemption", p1 = "E-Total Evidence", p0 = "E-Preemption")
)

contrast_metrics <- data.frame(
  metric = c(
    "post_regret", "early_wrong_rate", "post_correct_rate", "post_payoff",
    "post_b_pulls", "final_truth_mass", "late_wrong_rate"
  ),
  column = c(
    "mean_lay_post_intervention_regret", "early_window_wrong_choice_rate",
    "post_intervention_correct_choice_rate", "post_intervention_realized_payoff",
    "mean_lay_post_intervention_b_pulls", "mean_lay_posterior_truth_mass",
    "final_window_wrong_choice_rate"
  ),
  favorable_direction = c("lower", "lower", "higher", "higher", "mechanism", "higher", "lower"),
  stringsAsFactors = FALSE
)

paired_difference <- function(data, world, p1, p0, column, status = NULL) {
  d <- data[data$hidden_world == world, ]
  if (!is.null(status)) d <- d[d$expert_status == status, ]
  a <- d[d$evidence_policy == p1, c("actual_seed", column)]
  b <- d[d$evidence_policy == p0, c("actual_seed", column)]
  names(a)[[2]] <- "a"
  names(b)[[2]] <- "b"
  m <- merge(a, b, by = "actual_seed", all = FALSE)
  m <- m[order(m$actual_seed), ]
  list(seed = m$actual_seed, difference = as.numeric(m$a) - as.numeric(m$b))
}

contrast_rows <- list()
contrast_index <- 1L
for (w in worlds) {
  for (spec in contrast_specs) {
    for (j in seq_len(nrow(contrast_metrics))) {
      metric_row <- contrast_metrics[j, ]
      d <- paired_difference(main, w, spec$p1, spec$p0, metric_row$column)
      ci <- bootstrap_mean_ci(d$difference, seed = 5000 + contrast_index)
      contrast_rows[[contrast_index]] <- data.frame(
        world = w,
        comparison = spec$label,
        policy_1 = spec$p1,
        policy_0 = spec$p0,
        metric = metric_row$metric,
        favorable_direction = metric_row$favorable_direction,
        n_pairs = length(d$difference),
        estimate = ci[["estimate"]],
        ci_low = ci[["low"]],
        ci_high = ci[["high"]],
        stringsAsFactors = FALSE
      )
      contrast_index <- contrast_index + 1L
    }
  }
}
paired_contrasts <- do.call(rbind, contrast_rows)
write_csv_utf8(paired_contrasts, "paired_contrasts.csv")

status_counts <- unique(main[main$evidence_policy == "No Deference", c(
  "hidden_world", "actual_seed", "expert_status"
)])
status_counts <- aggregate(
  actual_seed ~ hidden_world + expert_status,
  status_counts,
  length
)
names(status_counts) <- c("world", "expert_status", "n_paired_blocks")
write_csv_utf8(status_counts, "expert_status_counts.csv")

conditional_rows <- list()
conditional_index <- 1L
conditional_metrics <- contrast_metrics[contrast_metrics$metric %in% c(
  "post_regret", "early_wrong_rate", "post_correct_rate", "post_b_pulls", "late_wrong_rate"
), ]
for (w in worlds) {
  statuses <- unique(main$expert_status[main$hidden_world == w])
  for (status in c("Correct", "Incorrect", "Tie")) {
    if (!status %in% statuses) next
    for (spec in contrast_specs) {
      for (j in seq_len(nrow(conditional_metrics))) {
        metric_row <- conditional_metrics[j, ]
        d <- paired_difference(main, w, spec$p1, spec$p0, metric_row$column, status)
        if (length(d$difference) == 0) next
        ci <- bootstrap_mean_ci(d$difference, seed = 10000 + conditional_index)
        conditional_rows[[conditional_index]] <- data.frame(
          world = w,
          expert_status = status,
          comparison = spec$label,
          metric = metric_row$metric,
          n_pairs = length(d$difference),
          estimate = ci[["estimate"]],
          ci_low = ci[["low"]],
          ci_high = ci[["high"]],
          stringsAsFactors = FALSE
        )
        conditional_index <- conditional_index + 1L
      }
    }
  }
}
conditional_contrasts <- do.call(rbind, conditional_rows)
write_csv_utf8(conditional_contrasts, "conditional_paired_contrasts.csv")

# Attach the expert-status classification from the final paired experiment.
status_lookup <- unique(main[main$evidence_policy == "No Deference", c(
  "actual_seed", "hidden_world", "expert_status"
)])
trajectory <- merge(
  trajectory,
  status_lookup,
  by = c("actual_seed", "hidden_world"),
  all.x = TRUE,
  sort = FALSE
)
trajectory <- trajectory[order(
  trajectory$hidden_world,
  trajectory$actual_seed,
  match(trajectory$evidence_policy, policies),
  trajectory$ticks
), ]

trajectory_means <- aggregate(
  cbind(
    current_lay_correct_choice_rate,
    current_lay_b_share,
    current_lay_wrong_posterior_share,
    mean_lay_posterior_truth_mass,
    mean_lay_cumulative_regret,
    mean_lay_post_intervention_regret,
    mean_lay_b_pulls
  ) ~ hidden_world + evidence_policy + ticks,
  trajectory,
  mean
)

trajectory_sd <- aggregate(
  cbind(
    current_lay_correct_choice_rate,
    current_lay_b_share,
    mean_lay_posterior_truth_mass
  ) ~ hidden_world + evidence_policy + ticks,
  trajectory,
  sd
)
names(trajectory_sd)[4:6] <- c("correct_sd", "b_share_sd", "truth_mass_sd")
trajectory_n <- aggregate(
  actual_seed ~ hidden_world + evidence_policy + ticks,
  trajectory,
  length
)
names(trajectory_n)[[4]] <- "n_runs"
trajectory_summary <- merge(
  merge(trajectory_means, trajectory_sd, by = c("hidden_world", "evidence_policy", "ticks")),
  trajectory_n,
  by = c("hidden_world", "evidence_policy", "ticks")
)
trajectory_summary$correct_ci_low <- pmax(
  0,
  trajectory_summary$current_lay_correct_choice_rate -
    1.96 * trajectory_summary$correct_sd / sqrt(trajectory_summary$n_runs)
)
trajectory_summary$correct_ci_high <- pmin(
  1,
  trajectory_summary$current_lay_correct_choice_rate +
    1.96 * trajectory_summary$correct_sd / sqrt(trajectory_summary$n_runs)
)
trajectory_summary$world <- trajectory_summary$hidden_world
trajectory_summary$policy <- trajectory_summary$evidence_policy
trajectory_summary <- trajectory_summary[order(
  trajectory_summary$world,
  match(trajectory_summary$policy, policies),
  trajectory_summary$ticks
), ]
write_csv_utf8(trajectory_summary, "trajectory_summary.csv")

chart_ticks <- sort(unique(c(seq(0, 500, by = 5), 25, 26)))
trajectory_chart <- trajectory_summary[trajectory_summary$ticks %in% chart_ticks, c(
  "world", "policy", "ticks", "current_lay_correct_choice_rate",
  "correct_ci_low", "correct_ci_high", "current_lay_b_share",
  "mean_lay_posterior_truth_mass", "mean_lay_post_intervention_regret", "n_runs"
)]
names(trajectory_chart)[names(trajectory_chart) == "current_lay_correct_choice_rate"] <- "correct_choice_rate"
names(trajectory_chart)[names(trajectory_chart) == "current_lay_b_share"] <- "b_share"
names(trajectory_chart)[names(trajectory_chart) == "mean_lay_posterior_truth_mass"] <- "truth_mass"
names(trajectory_chart)[names(trajectory_chart) == "mean_lay_post_intervention_regret"] <- "post_regret"
write_csv_utf8(trajectory_chart, "trajectory_chart_data.csv")

conditional_path_data <- trajectory[
  trajectory$ticks >= 26 & trajectory$ticks <= 150,
]
conditional_path_summary <- aggregate(
  cbind(current_lay_correct_choice_rate, current_lay_b_share) ~
    hidden_world + expert_status + evidence_policy + ticks,
  conditional_path_data,
  mean
)
conditional_path_n <- aggregate(
  actual_seed ~ hidden_world + expert_status + evidence_policy + ticks,
  conditional_path_data,
  length
)
names(conditional_path_n)[[5]] <- "n_runs"
conditional_path_summary <- merge(
  conditional_path_summary,
  conditional_path_n,
  by = c("hidden_world", "expert_status", "evidence_policy", "ticks")
)
write_csv_utf8(conditional_path_summary, "conditional_path_summary.csv")

compute_recovery <- function(d) {
  d <- d[order(d$ticks), ]
  d <- d[d$ticks >= 26 & d$ticks <= 500, ]
  if (nrow(d) < 20) return(NA_real_)
  windows <- vapply(
    seq_len(nrow(d) - 19),
    function(i) mean(d$current_lay_correct_choice_rate[i:(i + 19)]),
    numeric(1)
  )
  hit <- which(windows >= 0.60)
  if (length(hit) == 0) return(NA_real_)
  d$ticks[hit[[1]]]
}

trajectory_key <- interaction(
  trajectory$hidden_world,
  trajectory$evidence_policy,
  trajectory$actual_seed,
  drop = TRUE,
  lex.order = TRUE
)
recovery_list <- split(trajectory, trajectory_key)
recovery_rows <- lapply(recovery_list, function(d) {
  tick <- compute_recovery(d)
  data.frame(
    world = d$hidden_world[[1]],
    policy = d$evidence_policy[[1]],
    seed = d$actual_seed[[1]],
    expert_status = d$expert_status[[1]],
    recovery_tick = tick,
    recovery_delay = ifelse(is.na(tick), NA, tick - 25),
    censored = is.na(tick),
    stringsAsFactors = FALSE
  )
})
recovery_runs <- do.call(rbind, recovery_rows)
write_csv_utf8(recovery_runs, "recovery_run_level.csv")

recovery_groups <- split(
  recovery_runs,
  interaction(
    recovery_runs$world,
    recovery_runs$expert_status,
    recovery_runs$policy,
    drop = TRUE,
    lex.order = TRUE
  )
)
recovery_summary <- do.call(rbind, lapply(recovery_groups, function(d) {
  data.frame(
    world = d$world[[1]],
    expert_status = d$expert_status[[1]],
    policy = d$policy[[1]],
    n_runs = nrow(d),
    censored_rate = mean(d$censored),
    median_recovery_delay_uncensored = ifelse(
      all(d$censored),
      NA,
      median(d$recovery_delay[!d$censored])
    ),
    stringsAsFactors = FALSE
  )
}))
write_csv_utf8(recovery_summary, "recovery_summary.csv")

# Thompson calibration uses the preceding tick's posterior. Tick 26 is
# excluded because its action uses the unobserved immediate post-intervention
# posterior rather than the tick-25 pre-intervention posterior.
trajectory$lag_q <- ave(
  trajectory$mean_lay_q,
  interaction(trajectory$hidden_world, trajectory$evidence_policy, trajectory$actual_seed),
  FUN = function(v) c(NA, v[-length(v)])
)
calibration <- trajectory[
  trajectory$ticks >= 1 & trajectory$ticks != 26 & is.finite(trajectory$lag_q),
  c("lag_q", "current_lay_b_share")
]
calibration$q_bin <- cut(
  calibration$lag_q,
  breaks = seq(0, 1, by = 0.1),
  include.lowest = TRUE,
  right = TRUE
)
calibration_summary <- aggregate(
  cbind(lag_q, current_lay_b_share) ~ q_bin,
  calibration,
  mean
)
calibration_n <- aggregate(current_lay_b_share ~ q_bin, calibration, length)
names(calibration_n)[[2]] <- "n_agent_groups"
calibration_summary <- merge(calibration_summary, calibration_n, by = "q_bin")
calibration_summary$absolute_gap <- abs(
  calibration_summary$current_lay_b_share - calibration_summary$lag_q
)
write_csv_utf8(calibration_summary, "thompson_calibration.csv")

# Validation and cross-experiment regression checks.
checks <- list()
add_check <- function(name, pass, detail) {
  checks[[length(checks) + 1L]] <<- data.frame(
    check = name,
    pass = isTRUE(pass),
    detail = as.character(detail),
    stringsAsFactors = FALSE
  )
}

add_check("main_row_count", nrow(main) == 3000, sprintf("observed=%d expected=3000", nrow(main)))
cell_counts <- table(main$hidden_world, main$evidence_policy)
add_check(
  "balanced_500_runs_per_cell",
  all(cell_counts[worlds, policies] == 500),
  paste(as.vector(cell_counts[worlds, policies]), collapse = "; ")
)
paired_counts <- table(interaction(main$hidden_world, main$actual_seed))
add_check("three_policies_per_pair", all(paired_counts == 3), sprintf("range=%d..%d", min(paired_counts), max(paired_counts)))

pre_columns <- c(
  "expert_truth_mass_at_25", "expert_recommendation_score_at_25",
  "expert_informative_observations_at_25", "mean_lay_truth_mass_at_25",
  "mean_lay_recommendation_score_at_25", "mean_lay_informative_observations_at_25",
  "mean_lay_archive_size_at_25", "mean_lay_cumulative_regret_at_25",
  "mean_lay_correct_pulls_at_25", "mean_lay_b_pulls_at_25", "mean_lay_reward_at_25"
)
pair_key <- interaction(main$hidden_world, main$actual_seed)
pre_diffs <- vapply(pre_columns, function(column) range_within(main[[column]], pair_key), numeric(1))
add_check(
  "pre_intervention_histories_identical_across_policies",
  max(pre_diffs) < 1e-12,
  sprintf("maximum within-pair range=%.3g", max(pre_diffs))
)

add_check("expert_packet_size_125", all(main$expert_packet_size_at_intervention == 125), "all final runs")
add_check("expert_packet_ids_unique", all(as_flag(main$expert_packet_unique)), "all final runs")
add_check("inbox_empty_at_intervention", all(as_flag(main$inbox_empty_at_intervention)), "all final runs")
add_check("expert_local_overlap_zero", all(main$expert_local_overlap_count == 0), "all final runs")
add_check("single_broadcast", all(main$broadcast_count == 1), "all final runs")
add_check("local_archive_75_at_tick_25", all(abs(main$mean_lay_archive_size_at_25 - 75) < 1e-12), "peer sharing fixed on")
add_check("total_archive_200_immediately_after", all(abs(main$mean_lay_archive_size_post_intervention - 200) < 1e-12), "75 local + 125 expert")

expected_active <- ifelse(
  main$evidence_policy == "No Deference",
  75,
  ifelse(main$evidence_policy == "E-Preemption", 125, 200)
)
add_check(
  "active_item_counts_match_policy",
  max(abs(main$mean_lay_active_evidence_items_post_intervention - expected_active)) < 1e-12,
  "No Deference=75; E-Preemption=125; E-Total Evidence=200"
)

nd <- main$evidence_policy == "No Deference"
ep <- main$evidence_policy == "E-Preemption"
add_check(
  "no_deference_immediate_posterior_unchanged",
  max(abs(main$mean_lay_truth_mass_post_intervention[nd] - main$mean_lay_truth_mass_at_25[nd])) < 1e-12,
  "maximum absolute difference below 1e-12"
)
add_check(
  "preemption_uses_raw_expert_packet_only",
  max(abs(main$mean_lay_truth_mass_post_intervention[ep] - main$expert_truth_mass_at_25[ep])) < 1e-12 &&
    max(main$lay_q_dispersion_post_intervention[ep]) < 1e-12,
  "truth mass equals raw-packet posterior and lay dispersion is zero"
)

boolean_checks <- c(
  "network_structure_valid", "message_accounting_valid", "evidence_provenance_valid",
  "expert_evidence_provenance_valid", "expert_packet_valid", "intervention_structure_valid"
)
for (column in boolean_checks) {
  add_check(column, all(as_flag(main[[column]])), "all final runs")
}
add_check(
  "posterior_llr_identity",
  max(main$maximum_belief_identity_error) < 1e-10,
  sprintf("maximum=%.3g", max(main$maximum_belief_identity_error))
)
add_check(
  "regret_identity",
  max(main$maximum_regret_identity_error) < 1e-10,
  sprintf("maximum=%.3g", max(main$maximum_regret_identity_error))
)
add_check(
  "future_local_evidence_decomposition",
  max(main$maximum_decision_decomposition_error) < 1e-10,
  sprintf("maximum=%.3g", max(main$maximum_decision_decomposition_error))
)
add_check(
  "packet_llr_reconstructed_from_raw_records",
  max(main$maximum_expert_packet_llr_error) < 1e-10,
  sprintf("maximum=%.3g", max(main$maximum_expert_packet_llr_error))
)
add_check(
  "final_pull_counts",
  all(main$expert_total_pulls == 125) && all(main$total_lay_pulls == 5000),
  "expert=125 and laypeople total=5000"
)
add_check(
  "final_message_and_archive_accounting",
  all(abs(main$mean_peer_messages_received - 998) < 1e-12) &&
    all(abs(main$mean_unique_evidence_count - 1498) < 1e-12) &&
    all(abs(main$mean_expert_evidence_items_received - 125) < 1e-12) &&
    all(abs(main$mean_lay_total_archive_size - 1623) < 1e-12),
  "998 peer + 500 own local IDs; 125 expert records"
)

a_rate <- mean(main$lay_a_reward_rate)
b_good_rate <- mean(main$lay_b_reward_rate[main$hidden_world == "B-good"])
b_bad_rate <- mean(main$lay_b_reward_rate[main$hidden_world == "B-bad"])
add_check(
  "reward_frequencies_match_environment",
  abs(a_rate - 0.50) < 0.02 && abs(b_good_rate - 0.55) < 0.02 && abs(b_bad_rate - 0.45) < 0.02,
  sprintf("A=%.4f B-good=%.4f B-bad=%.4f", a_rate, b_good_rate, b_bad_rate)
)

add_check(
  "trajectory_row_count",
  nrow(trajectory) == 200 * 2 * 3 * 501,
  sprintf("observed=%d expected=%d", nrow(trajectory), 200 * 2 * 3 * 501)
)
trajectory_pre <- trajectory[trajectory$ticks <= 25, ]
trajectory_pre_key <- interaction(
  trajectory_pre$hidden_world,
  trajectory_pre$actual_seed,
  trajectory_pre$ticks
)
trajectory_pre_columns <- c(
  "current_lay_correct_choice_rate", "current_lay_b_share", "mean_lay_q",
  "mean_lay_posterior_truth_mass", "lay_q_dispersion",
  "mean_lay_cumulative_regret", "mean_lay_b_pulls",
  "expert_posterior_truth_mass", "expert_total_pulls"
)
trajectory_pre_diffs <- vapply(
  trajectory_pre_columns,
  function(column) range_within(trajectory_pre[[column]], trajectory_pre_key),
  numeric(1)
)
add_check(
  "pre_intervention_trajectories_identical_across_policies",
  max(trajectory_pre_diffs) < 1e-12,
  sprintf("maximum within-pair-tick range=%.3g", max(trajectory_pre_diffs))
)

# Experiment 1 No Deference must reproduce Experiment 0 exactly.
exp1_nd <- main[main$evidence_policy == "No Deference", ]
exp1_nd <- exp1_nd[order(exp1_nd$hidden_world, exp1_nd$actual_seed), ]
exp0_main <- exp0_main[order(exp0_main$hidden_world, exp0_main$actual_seed), ]
cross_main_columns <- intersect(c(
  "expert_truth_mass_at_25", "expert_recommendation_score_at_25",
  "expert_informative_observations_at_25", "mean_lay_truth_mass_at_25",
  "mean_lay_recommendation_score_at_25", "mean_lay_informative_observations_at_25",
  "mean_lay_archive_size_at_25", "mean_lay_posterior_truth_mass",
  "cumulative_lay_correct_choice_rate", "mean_lay_cumulative_regret",
  "mean_lay_realized_payoff", "mean_lay_b_pulls",
  "mean_lay_informative_observations", "final_window_wrong_choice_rate",
  "expert_posterior_truth_mass", "expert_cumulative_regret",
  "mean_peer_messages_received", "mean_unique_evidence_count"
), intersect(names(exp1_nd), names(exp0_main)))
cross_main_diff <- max(vapply(
  cross_main_columns,
  function(column) max_abs_difference(exp1_nd[[column]], exp0_main[[column]]),
  numeric(1)
))
add_check(
  "no_deference_reproduces_experiment_0_final",
  nrow(exp1_nd) == nrow(exp0_main) && cross_main_diff < 1e-12,
  sprintf("rows=%d; maximum difference=%.3g", nrow(exp1_nd), cross_main_diff)
)

exp1_nd_traj <- trajectory[trajectory$evidence_policy == "No Deference", ]
exp1_nd_traj <- exp1_nd_traj[order(
  exp1_nd_traj$hidden_world, exp1_nd_traj$actual_seed, exp1_nd_traj$ticks
), ]
exp0_trajectory <- exp0_trajectory[order(
  exp0_trajectory$hidden_world, exp0_trajectory$actual_seed, exp0_trajectory$ticks
), ]
cross_traj_columns <- intersect(c(
  "current_lay_correct_choice_rate", "current_lay_b_share", "mean_lay_q",
  "mean_lay_posterior_truth_mass", "lay_q_dispersion",
  "mean_lay_cumulative_regret", "mean_lay_b_pulls",
  "expert_posterior_truth_mass", "expert_total_pulls"
), intersect(names(exp1_nd_traj), names(exp0_trajectory)))
cross_traj_diff <- max(vapply(
  cross_traj_columns,
  function(column) max_abs_difference(exp1_nd_traj[[column]], exp0_trajectory[[column]]),
  numeric(1)
))
add_check(
  "no_deference_reproduces_experiment_0_trajectory",
  nrow(exp1_nd_traj) == nrow(exp0_trajectory) && cross_traj_diff < 1e-12,
  sprintf("rows=%d; maximum difference=%.3g", nrow(exp1_nd_traj), cross_traj_diff)
)

trajectory_early <- trajectory[
  trajectory$ticks >= 26 & trajectory$ticks <= 100,
]
trajectory_aue <- aggregate(
  current_lay_correct_choice_rate ~ hidden_world + evidence_policy + actual_seed,
  trajectory_early,
  function(v) 1 - mean(v)
)
names(trajectory_aue)[[4]] <- "trajectory_early_wrong"
main_for_aue <- main[main$actual_seed <= 310200, c(
  "hidden_world", "evidence_policy", "actual_seed", "early_window_wrong_choice_rate"
)]
aue_check <- merge(
  trajectory_aue,
  main_for_aue,
  by = c("hidden_world", "evidence_policy", "actual_seed")
)
add_check(
  "early_window_metric_matches_trajectory",
  max(abs(aue_check$trajectory_early_wrong - aue_check$early_window_wrong_choice_rate)) < 1e-12,
  sprintf("maximum difference=%.3g", max(abs(aue_check$trajectory_early_wrong - aue_check$early_window_wrong_choice_rate)))
)

max_calibration_gap <- max(calibration_summary$absolute_gap)
add_check(
  "thompson_sampling_calibration",
  max_calibration_gap < 0.06,
  sprintf("maximum 0.1-bin absolute gap=%.4f", max_calibration_gap)
)

validation_checks <- do.call(rbind, checks)
write_csv_utf8(validation_checks, "validation_checks.csv")

validation_lines <- c(
  "# Experiment 1 validation",
  "",
  sprintf("Passed %d of %d checks.", sum(validation_checks$pass), nrow(validation_checks)),
  "",
  paste0(
    "- ",
    ifelse(validation_checks$pass, "PASS", "FAIL"),
    " | ", validation_checks$check, ": ", validation_checks$detail
  )
)
writeLines(
  enc2utf8(validation_lines),
  file.path(output_dir, "validation_report.md"),
  useBytes = TRUE
)

headline_contrasts <- paired_contrasts[
  paired_contrasts$comparison == "E-Total Evidence - E-Preemption" &
    paired_contrasts$metric == "post_regret",
]
headline_contrasts$comparison_label <- paste(
  headline_contrasts$world,
  "E-Total Evidence minus E-Preemption"
)
write_csv_utf8(headline_contrasts, "headline_results.csv")

key_lines <- c(
  sprintf("validation_passed=%d/%d", sum(validation_checks$pass), nrow(validation_checks)),
  sprintf("main_runs=%d", nrow(main)),
  sprintf("trajectory_rows=%d", nrow(trajectory)),
  sprintf("reward_rates=A %.4f; B-good %.4f; B-bad %.4f", a_rate, b_good_rate, b_bad_rate)
)
for (i in seq_len(nrow(headline_contrasts))) {
  r <- headline_contrasts[i, ]
  key_lines <- c(key_lines, sprintf(
    "%s_TE_minus_P_post_regret=%.6f [%.6f, %.6f]",
    r$world, r$estimate, r$ci_low, r$ci_high
  ))
}
writeLines(
  enc2utf8(key_lines),
  file.path(output_dir, "analysis_key_results.txt"),
  useBytes = TRUE
)

chart_map <- c(
  "# Chart map",
  "",
  "- Learning paths: question = how deference changes subsequent correct-arm behavior; family = line; fields = tick, correct-choice rate, policy, world; palette = relaxed multi-category for three policies plus line-style redundancy; source = trajectory_chart_data.csv.",
  "- Paired regret contrasts: question = finite-horizon payoff difference versus matched alternatives; family = faceted bar with zero reference; fields = world, comparison, estimate and bootstrap interval; palette = single-root sequential; source = paired_contrasts.csv.",
  "- Expert-status mechanism table: question = whether expert-correct and expert-incorrect paths differ; form = exact table because multiple strata and uncertainty intervals require lookup; source = conditional_paired_contrasts.csv."
)
writeLines(enc2utf8(chart_map), file.path(output_dir, "chart_map.md"), useBytes = TRUE)

session_lines <- capture.output(sessionInfo())
writeLines(session_lines, file.path(output_dir, "R_session_info.txt"), useBytes = TRUE)

if (!all(validation_checks$pass)) {
  failed <- validation_checks$check[!validation_checks$pass]
  stop(sprintf("Validation failed: %s", paste(failed, collapse = ", ")))
}

cat("Analysis complete. All validation checks passed.\n")
