import pytest
import torch
from torch import eye, zeros, ones
from torch.distributions import MultivariateNormal

import sbi.utils as utils
from tests.test_utils import (
    check_c2st,
    get_prob_outside_uniform_prior,
    get_dkl_any_gaussian_prior,
)
from sbi.inference.sre.sre import SRE
from sbi.simulators.linear_gaussian import (
    true_posterior_linear_gaussian_mvn_prior,
    samples_true_posterior_linear_gaussian_uniform_prior,
    samples_true_posterior_linear_gaussian_mvn_prior_different_dims,
    standard_linear_gaussian,
    linear_gaussian_different_dims,
    linear_gaussian,
)

# use cpu by default
torch.set_default_tensor_type("torch.FloatTensor")
# Seeding:
# Some tests in this module have "set_seed" as an argument. This argument points to
# tests/conftest.py to seed the test with the seed set in conftext.py.


# @pytest.mark.parametrize("num_dim", (1, 3))
@pytest.mark.parametrize("num_dim", (3,))  # todo
def test_sre_on_linearGaussian_api(num_dim: int):
    """Test inference API of SRE with linear Gaussian model.

    Avoids intense computation for fast testing of API etc.

    Args:
        num_dim: parameter dimension of the Gaussian model
    """

    x_o = zeros(num_dim)
    prior = MultivariateNormal(loc=zeros(num_dim), covariance_matrix=eye(num_dim))

    infer = SRE(
        simulator=standard_linear_gaussian,
        prior=prior,
        x_o=x_o,
        classifier=None,  # Use default RESNET.
        simulation_batch_size=50,
        mcmc_method="slice_np",
    )

    posterior = infer(num_rounds=1, num_simulations_per_round=1000)

    posterior.sample(num_samples=10, num_chains=2)


@pytest.mark.slow
@pytest.mark.parametrize(
    "num_dim, prior_str, classifier_loss",
    (
        (2, "gaussian", "sre"),
        (1, "gaussian", "sre"),
        (2, "uniform", "sre"),
        (2, "gaussian", "aalr"),
    ),
)
def test_sre_on_linearGaussian_based_on_c2st(
    num_dim: int, prior_str: str, classifier_loss: str, set_seed,
):
    """Test c2st accuracy of inference with SRE on linear Gaussian model.

    Args:
        num_dim: parameter dimension of the gaussian model
        prior_str: one of "gaussian" or "uniform"
        set_seed: fixture for manual seeding
    """

    x_o = zeros(1, num_dim)
    num_samples = 300

    likelihood_shift = -1.0 * ones(
        num_dim
    )  # likelihood_mean will be likelihood_shift+theta
    likelihood_cov = 0.3 * eye(num_dim)

    if prior_str == "gaussian":
        prior_mean = zeros(num_dim)
        prior_cov = eye(num_dim)
        prior = MultivariateNormal(loc=prior_mean, covariance_matrix=prior_cov)
        gt_posterior = true_posterior_linear_gaussian_mvn_prior(
            x_o[0], likelihood_shift, likelihood_cov, prior_mean, prior_cov
        )
        target_samples = gt_posterior.sample((num_samples,))
    else:
        prior = utils.BoxUniform(-2.0 * ones(num_dim), 2.0 * ones(num_dim))
        target_samples = samples_true_posterior_linear_gaussian_uniform_prior(
            x_o, likelihood_shift, likelihood_cov, prior=prior, num_samples=num_samples
        )

    simulator = lambda theta: linear_gaussian(theta, likelihood_shift, likelihood_cov)

    num_atoms = 2 if classifier_loss == "aalr" else None

    infer = SRE(
        simulator=simulator,
        prior=prior,
        x_o=x_o,
        num_atoms=num_atoms,
        classifier=None,  # Use default RESNET.
        classifier_loss=classifier_loss,
        simulation_batch_size=50,
        mcmc_method="slice_np",
    )

    posterior = infer(num_rounds=1, num_simulations_per_round=1000)

    samples = posterior.sample(num_samples=num_samples)

    # # Check performance based on c2st accuracy.
    # check_c2st(samples, target_samples, alg=f"sre-{prior_str}-{classifier_loss}")

    # Checks for log_prob()
    if prior_str == "gaussian" and classifier_loss == "aalr":
        # For the Gaussian prior, we compute the KLd between ground truth and
        # posterior. We can do this only if the classifier_loss was as described in
        # Hermans et al. 2019 ('aalr') since Durkan et al. 2019 version only allows
        # evaluation up to a constant.
        # For the Gaussian prior, we compute the KLd between ground truth and posterior
        dkl = get_dkl_any_gaussian_prior(
            posterior, x_o[0], likelihood_shift, likelihood_cov, prior_mean, prior_cov
        )

        max_dkl = 0.05 if num_dim == 1 else 0.8

        assert (
            dkl < max_dkl
        ), f"KLd={dkl} is more than 2 stds above the average performance."
    if prior_str == "uniform":
        # Check whether the returned probability outside of the support is zero.
        posterior_prob = get_prob_outside_uniform_prior(posterior, num_dim)
        assert (
            posterior_prob == 0.0
        ), "The posterior probability outside of the prior support is not zero"


@pytest.mark.slow
def test_sre_on_linearGaussian_different_dims_based_on_c2st(set_seed):
    """Test whether SRE infers well a simple example with available round truth.

    This example has different number of parameters theta than number of x.

    Args:
        set_seed: fixture for manual seeding
    """

    theta_dim = 3
    x_dim = 2
    discard_dims = theta_dim - x_dim

    x_o = ones(1, x_dim)
    num_samples = 300

    likelihood_shift = -1.0 * ones(
        x_dim
    )  # likelihood_mean will be likelihood_shift+theta
    likelihood_cov = 0.3 * eye(x_dim)

    prior_mean = zeros(theta_dim)
    prior_cov = eye(theta_dim)
    prior = MultivariateNormal(loc=prior_mean, covariance_matrix=prior_cov)
    target_samples = samples_true_posterior_linear_gaussian_mvn_prior_different_dims(
        x_o[0],
        likelihood_shift,
        likelihood_cov,
        prior_mean,
        prior_cov,
        num_discarded_dims=discard_dims,
        num_samples=num_samples,
    )

    simulator = lambda theta: linear_gaussian_different_dims(
        theta, likelihood_shift, likelihood_cov, num_discarded_dims=discard_dims
    )

    infer = SRE(
        simulator=simulator,
        prior=prior,
        x_o=x_o,
        classifier=None,  # Use default RESNET.
        simulation_batch_size=50,
    )

    posterior = infer(num_rounds=1, num_simulations_per_round=1000)  # type: ignore
    samples = posterior.sample(num_samples)

    # # Compute the c2st and assert it is near chance level of 0.5.
    # check_c2st(samples, target_samples, alg="snpe_c")


@pytest.mark.slow
@pytest.mark.parametrize(
    "mcmc_method, prior_str",
    (
        ("slice_np", "gaussian"),
        ("slice_np", "uniform"),
        ("slice", "gaussian"),
        ("slice", "uniform"),
    ),
)
def test_sre_posterior_correction(mcmc_method: str, prior_str: str, set_seed):
    """Test leakage correction both for MCMC and rejection sampling.

    Args:
        mcmc_method: which mcmc method to use for sampling
        prior_str: one of "gaussian" or "uniform"
        set_seed: fixture for manual seeding
    """

    num_dim = 2
    x_o = zeros(num_dim)
    if prior_str == "gaussian":
        prior = MultivariateNormal(loc=zeros(num_dim), covariance_matrix=eye(num_dim))
    else:
        prior = utils.BoxUniform(low=-1.0 * ones(num_dim), high=ones(num_dim))

    infer = SRE(
        simulator=standard_linear_gaussian,
        prior=prior,
        x_o=x_o,
        classifier=None,  # Use default RESNET.
        simulation_batch_size=50,
        mcmc_method=mcmc_method,
    )

    posterior = infer(num_rounds=1, num_simulations_per_round=1000)

    posterior.sample(num_samples=30)
