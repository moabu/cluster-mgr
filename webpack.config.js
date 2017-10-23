const webpack = require('webpack');
const path = require('path');
const CleanWebpackPlugin = require('clean-webpack-plugin');


module.exports = {
    entry: {
        main: './uijs/Logger.js',
        vendor: [
            'react', 'react-dom', 'axios'
        ]

    },
    output: {
        path: path.resolve(__dirname, 'clustermgr/static/build'),
        filename: "[name].[chunkhash].js"
    },
    module: {
        rules: [
            { test: /\.js$/, exclude: /node_modules/, loader: "babel-loader" },
            { test: /\.css$/, use: 'css-loader' },
        ]
    },
    plugins: [
        new CleanWebpackPlugin(['clustermgr/static/build']),
        new webpack.optimize.CommonsChunkPlugin({
            name: 'vendor'
        }),
        new webpack.optimize.CommonsChunkPlugin({
            name: 'runtime'
        }),
    ]
}
