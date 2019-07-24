node() {
    def scmVars = null
    def metricsImage = null

    stage('Checkout') {
        scmVars = checkout(scm)
    }
    stage('Build') {
        metricsImage = docker.build('metrics:master')
    }
    stage('Test') {
        metricsImage.inside {
            sh(script: 'python -m unittest discover ./tests')
        }
    }
    stage('Push') {
        // push it
    }
}