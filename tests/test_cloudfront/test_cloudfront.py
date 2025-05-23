import boto3
import pytest
from botocore.exceptions import ClientError

from moto import mock_aws
from moto.core import DEFAULT_ACCOUNT_ID as ACCOUNT_ID

from . import cloudfront_test_scaffolding as scaffold

# See our Development Tips on writing tests for hints on how to write good tests:
# http://docs.getmoto.org/en/latest/docs/contributing/development_tips/tests.html


@mock_aws
def test_update_distribution():
    client = boto3.client("cloudfront", region_name="us-east-1")

    # Create standard distribution
    config = scaffold.example_distribution_config(ref="ref")
    dist = client.create_distribution(DistributionConfig=config)
    dist_id = dist["Distribution"]["Id"]
    dist_etag = dist["ETag"]

    dist_config = dist["Distribution"]["DistributionConfig"]
    aliases = ["alias1", "alias2"]
    dist_config["Origins"]["Items"][0]["OriginPath"] = "/updated"
    dist_config["Aliases"] = {"Quantity": len(aliases), "Items": aliases}

    dist = client.update_distribution(
        DistributionConfig=dist_config, Id=dist_id, IfMatch=dist_etag
    )["Distribution"]
    assert dist["ARN"] == f"arn:aws:cloudfront:{ACCOUNT_ID}:distribution/{dist['Id']}"
    assert dist["Status"] == "Deployed"
    assert "LastModifiedTime" in dist
    assert dist["InProgressInvalidationBatches"] == 0
    assert ".cloudfront.net" in dist["DomainName"]

    assert dist["ActiveTrustedSigners"] == {
        "Enabled": False,
        "Items": [],
        "Quantity": 0,
    }

    assert dist["ActiveTrustedKeyGroups"] == {
        "Enabled": False,
        "Items": [],
        "Quantity": 0,
    }

    config = dist["DistributionConfig"]
    assert config["CallerReference"] == "ref"

    assert config["Aliases"] == dist_config["Aliases"]

    origins = config["Origins"]
    assert origins["Quantity"] == 1
    assert len(origins["Items"]) == 1
    origin = origins["Items"][0]
    assert origin["Id"] == "origin1"
    assert origin["DomainName"] == "asdf.s3.us-east-1.amazonaws.com"
    assert origin["OriginPath"] == "/updated"

    assert origin["CustomHeaders"]["Quantity"] == 0

    assert origin["ConnectionAttempts"] == 3
    assert origin["ConnectionTimeout"] == 10
    assert origin["OriginShield"] == {"Enabled": False, "OriginShieldRegion": "None"}

    assert config["OriginGroups"] == {"Quantity": 0}

    default_cache = config["DefaultCacheBehavior"]
    assert default_cache["TargetOriginId"] == "origin1"

    signers = default_cache["TrustedSigners"]
    assert signers["Enabled"] is False
    assert signers["Quantity"] == 0

    groups = default_cache["TrustedKeyGroups"]
    assert groups["Enabled"] is False
    assert groups["Quantity"] == 0

    assert default_cache["ViewerProtocolPolicy"] == "allow-all"

    methods = default_cache["AllowedMethods"]
    assert methods["Quantity"] == 2
    assert set(methods["Items"]) == {"HEAD", "GET"}

    cached_methods = methods["CachedMethods"]
    assert cached_methods["Quantity"] == 2
    assert set(cached_methods["Items"]) == {"HEAD", "GET"}

    assert default_cache["SmoothStreaming"] is False
    assert default_cache["Compress"] is True
    assert default_cache["LambdaFunctionAssociations"] == {"Quantity": 0}
    assert default_cache["FunctionAssociations"] == {"Quantity": 0}
    assert default_cache["FieldLevelEncryptionId"] == ""
    assert "CachePolicyId" in default_cache

    assert config["CacheBehaviors"] == {"Quantity": 0}
    assert config["CustomErrorResponses"] == {"Quantity": 0}
    assert config["Comment"] == "an optional comment that's not actually optional"

    logging = config["Logging"]
    assert logging["Enabled"] is False
    assert logging["IncludeCookies"] is False
    assert logging["Bucket"] == ""
    assert logging["Prefix"] == ""

    assert config["PriceClass"] == "PriceClass_All"
    assert config["Enabled"] is False
    assert "WebACLId" in config
    assert config["HttpVersion"] == "http2"
    assert config["IsIPV6Enabled"] is True

    cert = config["ViewerCertificate"]
    assert cert["CloudFrontDefaultCertificate"] is True
    assert cert["MinimumProtocolVersion"] == "TLSv1"
    assert cert["CertificateSource"] == "cloudfront"
    assert cert["IAMCertificateId"] == ""
    assert cert["ACMCertificateArn"] == ""
    assert cert["SSLSupportMethod"] == "sni-only"

    restriction = config["Restrictions"]["GeoRestriction"]
    assert restriction["RestrictionType"] == "none"
    assert restriction["Quantity"] == 0


@mock_aws
def test_update_distribution_no_such_distId():
    client = boto3.client("cloudfront", region_name="us-east-1")

    # Create standard distribution
    config = scaffold.example_distribution_config(ref="ref")
    dist = client.create_distribution(DistributionConfig=config)

    # Make up a fake dist ID by reversing the actual ID
    dist_id = dist["Distribution"]["Id"][::-1]
    dist_etag = dist["ETag"]

    dist_config = dist["Distribution"]["DistributionConfig"]
    aliases = ["alias1", "alias2"]
    dist_config["Aliases"] = {"Quantity": len(aliases), "Items": aliases}

    with pytest.raises(ClientError) as error:
        client.update_distribution(
            DistributionConfig=dist_config, Id=dist_id, IfMatch=dist_etag
        )

    metadata = error.value.response["ResponseMetadata"]
    assert metadata["HTTPStatusCode"] == 404
    err = error.value.response["Error"]
    assert err["Code"] == "NoSuchDistribution"
    assert err["Message"] == "The specified distribution does not exist."


@mock_aws
def test_update_distribution_IfMatch_not_set():
    client = boto3.client("cloudfront", region_name="us-east-1")

    # Create standard distribution
    config = scaffold.example_distribution_config(ref="ref")
    dist = client.create_distribution(DistributionConfig=config)

    # Make up a fake dist ID by reversing the actual ID
    dist_id = dist["Distribution"]["Id"]

    dist_config = dist["Distribution"]["DistributionConfig"]
    aliases = ["alias1", "alias2"]
    dist_config["Aliases"] = {"Quantity": len(aliases), "Items": aliases}

    with pytest.raises(ClientError) as error:
        client.update_distribution(
            DistributionConfig=dist_config, Id=dist_id, IfMatch=""
        )

    metadata = error.value.response["ResponseMetadata"]
    assert metadata["HTTPStatusCode"] == 400
    err = error.value.response["Error"]
    assert err["Code"] == "InvalidIfMatchVersion"
    msg = "The If-Match version is missing or not valid for the resource."
    assert err["Message"] == msg


@mock_aws
def test_update_default_root_object():
    client = boto3.client("cloudfront", region_name="us-east-1")

    config = scaffold.minimal_dist_custom_config("sth")
    dist = client.create_distribution(DistributionConfig=config)

    dist_id = dist["Distribution"]["Id"]
    root_object = "index.html"
    dist_config = client.get_distribution_config(Id=dist_id)

    # Update the default root object
    dist_config["DistributionConfig"]["DefaultRootObject"] = root_object

    client.update_distribution(
        DistributionConfig=dist_config["DistributionConfig"],
        Id=dist_id,
        IfMatch=dist_config["ETag"],
    )

    dist_config = client.get_distribution_config(Id=dist_id)
    assert dist_config["DistributionConfig"]["DefaultRootObject"] == "index.html"


@mock_aws
def test_update_distribution_applies_changes():
    client = boto3.client("cloudfront", region_name="us-east-1")

    # Create standard distribution
    config = scaffold.example_distribution_config(ref="ref")
    dist = client.create_distribution(DistributionConfig=config)
    dist_id = dist["Distribution"]["Id"]

    # Assert that default 'Enabled' value is false
    actual_dist_config = client.get_distribution(Id=dist_id)["Distribution"][
        "DistributionConfig"
    ]
    assert not actual_dist_config["Enabled"]

    # Update 'Enabled' value to true
    get_config_response = client.get_distribution_config(Id=dist_id)
    actual_dist_config = get_config_response["DistributionConfig"]
    etag = get_config_response["ETag"]
    actual_dist_config["Enabled"] = True
    client.update_distribution(
        DistributionConfig=actual_dist_config, Id=dist_id, IfMatch=etag
    )

    # Assert that 'Enabled' value is true
    actual_dist_config = client.get_distribution(Id=dist_id)["Distribution"][
        "DistributionConfig"
    ]
    assert actual_dist_config["Enabled"]


@mock_aws
def test_update_distribution_trusted_signers():
    client = boto3.client("cloudfront", region_name="us-east-1")

    # Create standard distribution
    config = scaffold.example_distribution_config(ref="ref")

    dist = client.create_distribution(DistributionConfig=config)
    dist_id = dist["Distribution"]["Id"]

    # Assert that default TrustedSigners 'Enabled' value is false
    actual_dist_config = client.get_distribution(Id=dist_id)["Distribution"][
        "DistributionConfig"
    ]
    assert (
        actual_dist_config["DefaultCacheBehavior"]["TrustedSigners"]["Enabled"] is False
    )

    # Add an item to TrustedSigners
    get_config_response = client.get_distribution_config(Id=dist_id)
    actual_dist_config = get_config_response["DistributionConfig"]
    etag = get_config_response["ETag"]
    actual_dist_config["DefaultCacheBehavior"]["TrustedSigners"]["Items"] = [
        "AwsAccountNumber123"
    ]

    client.update_distribution(
        DistributionConfig=actual_dist_config, Id=dist_id, IfMatch=etag
    )

    # Assert that all TrustedSigners fields updated
    updated_dist_config = client.get_distribution(Id=dist_id)["Distribution"][
        "DistributionConfig"
    ]
    assert (
        updated_dist_config["DefaultCacheBehavior"]["TrustedSigners"]["Quantity"] == 1
    )
    assert updated_dist_config["DefaultCacheBehavior"]["TrustedSigners"]["Enabled"]
    assert (
        "AwsAccountNumber123"
        in updated_dist_config["DefaultCacheBehavior"]["TrustedSigners"]["Items"]
    )
