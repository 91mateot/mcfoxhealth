"""Offline SAM expansion and narrow-policy checks. No AWS clients or reads."""
import json
from pathlib import Path
from types import SimpleNamespace
from samtranslator.translator.transform import transform
from samtranslator.yaml_helper import yaml_parse


def main():
    root = Path(__file__).resolve().parents[1]
    template = yaml_parse((root / 'prism-steps.template.yaml').read_text())
    parameters = json.loads((root / 'release/prism-steps-daily.parameters.json').read_text())
    parameters['StepsSecretArn'] = 'arn:aws:secretsmanager:us-west-2:000000000000:secret:prism-steps-read-review-synthetic'
    # Translation expects packaged URIs; synthetic placeholders, no upload.
    template['Resources']['StepsFunction']['Properties']['CodeUri'] = 's3://offline-review/function.zip'
    template['Resources']['SharedLayer']['Properties']['ContentUri'] = 's3://offline-review/layer.zip'
    expanded = transform(template, parameters, managed_policy_loader=SimpleNamespace(load=lambda: {
        'AWSLambdaBasicExecutionRole': 'arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole'}))
    resources = expanded['Resources']
    assert sorted(r['Type'] for r in resources.values()) == sorted([
        'AWS::ApiGatewayV2::Api', 'AWS::ApiGatewayV2::Stage', 'AWS::Lambda::Function',
        'AWS::IAM::Role', 'AWS::Lambda::Permission', 'AWS::Lambda::LayerVersion'])
    role = next(r['Properties'] for r in resources.values() if r['Type'] == 'AWS::IAM::Role')
    policies = role['Policies']
    assert len(policies) == 1
    policy = policies[0]['PolicyDocument']
    assert [s['Action'] for s in policy['Statement']] == ['dynamodb:GetItem', 'secretsmanager:GetSecretValue']
    keys = policy['Statement'][0]['Condition']['ForAllValues:StringEquals']['dynamodb:LeadingKeys']
    assert keys['Fn::If'][0] == 'DailyMode'
    assert keys['Fn::If'][2] == [{'Ref': 'AllowedDate'}]
    dates = parameters['DailyApprovedDates'].split(',')
    # Resolve only this reviewed branch; this is not a general IAM simulator.
    policy['Statement'][0]['Condition']['ForAllValues:StringEquals']['dynamodb:LeadingKeys'] = dates
    assert len(dates) == 92 and len(set(dates)) == 92
    encoded = json.dumps(policy, separators=(',', ':'))
    assert len(encoded) < 10240
    assert len(parameters['DailyApprovedDates']) < 4096
    assert '*' not in encoded
    print(json.dumps({'sam_resources': len(resources), 'inline_policy_bytes': len(encoded),
                      'date_parameter_bytes': len(parameters['DailyApprovedDates']),
                      'partition_keys': len(dates), 'aws_calls': 0}))


if __name__ == '__main__':
    main()
