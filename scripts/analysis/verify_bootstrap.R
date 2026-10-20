args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 2) stop("Usage: Rscript verify_bootstrap.R <audit-values.csv> <output.csv>")
input <- read.csv(args[[1]], stringsAsFactors = FALSE)
ids <- unique(input$job)
out <- lapply(ids, function(id) {
  d <- input[input$job == id, ]
  x <- d$value
  stopifnot(length(x) > 1, all(is.finite(x)))
  set.seed(d$seed[[1]])
  b <- d$replicates[[1]]
  draws <- replicate(b, mean(sample(x, length(x), replace = TRUE)))
  ci <- quantile(draws, c(.025, .975), names = FALSE, type = 7)
  data.frame(job = id, n = length(x), mean = mean(x), ci_low = ci[[1]], ci_high = ci[[2]])
})
write.csv(do.call(rbind, out), args[[2]], row.names = FALSE)
